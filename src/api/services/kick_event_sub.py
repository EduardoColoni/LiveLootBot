import rsa
import base64
import json
from fastapi import APIRouter, Request, Header, HTTPException
from fastapi.responses import JSONResponse
from src.database.redis.connection.redis_connection import RedisConnectionHandle
from src.database.redis.redis_repository import RedisRepository


class KickEventSubController:
    """
    Controlador para receber e processar webhooks da Kick.
    """
    KICK_PUBLIC_KEY = """
-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAq/+l1WnlRrGSolDMA+A8
6rAhMbQGmQ2SapVcGM3zq8ANXjnhDWocMqfWcTd95btDydITa10kDvHzw9WQOqp2
MZI7ZyrfzJuz5nhTPCiJwTwnEtWft7nV14BYRDHvlfqPUaZ+1KR4OCaO/wWIk/rQ
L/TjY0M70gse8rlBkbo2a8rKhu69RQTRsoaf4DVhDPEeSeI5jVrRDGAMGL3cGuyY
6CLKGdjVEM78g3JfYOvDU/RvfqD7L89TZ3iN94jrmWdGz34JNlEI5hqK8dd7C5EF
BEbZ5jgB8s8ReQV8H+MkuffjdAj3ajDDX3DOJMIut1lBrUVD1AaSrGCKHooWoL2e
twIDAQAB
-----END PUBLIC KEY-----
"""

    def __init__(self):
        self.redis_conn = RedisConnectionHandle().connect()
        self.router = APIRouter()
        self.router.add_api_route("/kick/eventsub", self.kick_eventsub, methods=["POST"])

        try:
            self.public_key = rsa.PublicKey.load_pkcs1_openssl_pem(self.KICK_PUBLIC_KEY.encode('utf-8'))
        except Exception as e:
            raise RuntimeError(f"Erro ao carregar a chave pública da Kick: {e}")

    async def kick_eventsub(
            self,
            request: Request,
            kick_message_id: str = Header(..., alias="Kick-Event-Message-Id"),
            kick_timestamp: str = Header(..., alias="Kick-Event-Message-Timestamp"),
            kick_signature: str = Header(..., alias="Kick-Event-Signature"),
            kick_message_type: str = Header(..., alias="Kick-Event-Type"),
            kick_subscription_id: str = Header(..., alias="Kick-Event-Subscription-Id")
    ):
        redis_repository = RedisRepository(self.redis_conn)
        body = await request.body()

        # 🔒 Validação da assinatura com RSA
        try:
            signature_to_verify = f"{kick_message_id}.{kick_timestamp}.{body.decode('utf-8')}"
            decoded_signature = base64.b64decode(kick_signature)

            rsa.verify(signature_to_verify.encode('utf-8'), decoded_signature, self.public_key)

        except (rsa.VerificationError, base64.binascii.Error) as e:
            print(f"Erro de verificação da assinatura: {e}")
            raise HTTPException(status_code=403, detail="Invalid signature")

        # Diferentemente da Twitch, a Kick não usa um "challenge".
        # A validação da assinatura é suficiente para confirmar a autenticidade.

        # 📩 Processamento do evento
        # Conforme a doc, o tipo de evento é "Kick-Event-Type"
        # O corpo do evento é o JSON
        data = json.loads(body.decode("utf-8"))

        print(f"Webhook recebido da Kick, tipo: {kick_message_type}")

        if kick_message_type == "chat.message.sent":
            event = data
            broadcaster_id = event["broadcaster"]["user_id"]
            sender_username = event["sender"]["username"]
            message_content = event["content"]

            print(f"[Chat Kick] {sender_username}: {message_content} no canal de {event['broadcaster']['username']}")

            # Exemplo de lógica similar ao seu código da Twitch
            redis_key = f"kick:{broadcaster_id}:{sender_username}"
            if message_content == "!claim":
                # AQUI: Lógica de processamento e salvamento no Redis
                redis_repository.insert_ex(redis_key, sender_username, 17)
                print(f"Comando !claim recebido. Usuário: {sender_username}")

        elif kick_message_type == "channel.followed":
            follower_username = data["follower"]["username"]
            print(f"[Follow Kick] Novo seguidor: {follower_username}")

        # Adicionar outros tipos de eventos conforme a necessidade
        # ...

        return JSONResponse(content={"status": "ok"})


def kick_event_sub_routes():
    controller = KickEventSubController()
    return controller.router