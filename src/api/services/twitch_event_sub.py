from fastapi import APIRouter, Request, Header
from fastapi.responses import PlainTextResponse, Response
import hmac
import hashlib
import json

from src.core.config import twitch
from src.core.criptografia import get_webhook_secret
from src.database.redis.connection.redis_connection import RedisConnectionHandle
from src.database.redis.redis_repository import RedisRepository


class TwitchEventSubController:
    def __init__(self):
        self.redis_conn = RedisConnectionHandle().connect()
        self.router = APIRouter()
        # Adiciona a rota apontando para o metodo de instância
        self.router.add_api_route(
            "/twitch/eventsub",
            self.twitch_eventsub,
            methods=["POST"]
        )

    async def twitch_eventsub(
        self,
        request: Request,
        twitch_message_id: str = Header(..., alias="Twitch-Eventsub-Message-Id"),
        twitch_timestamp: str = Header(..., alias="Twitch-Eventsub-Message-Timestamp"),
        twitch_signature: str = Header(..., alias="Twitch-Eventsub-Message-Signature"),
        twitch_message_type: str = Header(..., alias="Twitch-Eventsub-Message-Type"),
    ):
        redis_repository = RedisRepository(self.redis_conn)
        WEBHOOK_SECRET = get_webhook_secret()

        # Lê o corpo da requisição
        body = await request.body()

        # 🔒 Validação HMAC
        computed_hmac = hmac.new(
            WEBHOOK_SECRET.encode(),
            msg=(twitch_message_id + twitch_timestamp + body.decode()).encode(),
            digestmod=hashlib.sha256
        ).hexdigest()

        expected_signature = f"sha256={computed_hmac}"
        if not hmac.compare_digest(expected_signature, twitch_signature):
            # 403, e não 200: assim a Twitch registra a falha de entrega e o
            # log da API mostra que a assinatura não bateu.
            print(f"[EventSub] Assinatura inválida na mensagem {twitch_message_id}")
            return Response(status_code=403)

        # 🔄 Caso seja o challenge (verificação inicial)
        if twitch_message_type == "webhook_callback_verification":
            data = await request.json()
            # retorna apenas o texto do challenge, conforme exigido pelo Twitch
            return PlainTextResponse(data["challenge"])

        # 📩 Evento normal (mensagem de chat)
        if twitch_message_type == "notification":
            data = await request.json()
            event = data["event"]

            broadcaster_id = event['broadcaster_user_id']
            chatter_id = event['chatter_user_id']
            chatter_user_name = event['chatter_user_name']
            chatter_message = event['message']['text']

            # As mensagens do próprio bot também voltam por aqui. Sem isso elas
            # viram ruído no log e, no limite, o bot daria claim em si mesmo.
            if str(chatter_id) == str(twitch["BOT_PLATFORM_ID"]):
                return {"status": "ok"}

            # Canal e quem falou, os dois por id: pode haver mais de uma live ao
            # mesmo tempo, e o mesmo viewer pode estar em duas delas.
            redis_key = f"claim:twitch:{broadcaster_id}:{chatter_id}"
            print(f"Esse é a key do redis ->>>>: {redis_key}")

            if chatter_message == "!claim":
                # Aqui você pode salvar no Redis ou processar conforme seu fluxo
                redis_repository.insert_ex(redis_key, chatter_user_name, 17)
                print(f"[Chat] {event['chatter_user_name']}: {event['message']['text']}, {event['broadcaster_user_id']}\n")
                print(f"[Chat] {event}")

                print(f"\n teste: {redis_repository.get(redis_key)}")
                # Exemplo de salvar no Redis
                #self.redis_conn.set(f"twitch:chat:{event['id']}", json.dumps(event))

        return {"status": "ok"}


def twitch_event_sub_routes():
    controller = TwitchEventSubController()
    return controller.router
