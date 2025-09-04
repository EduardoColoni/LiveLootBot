from fastapi import APIRouter, Request, Header
from fastapi.responses import PlainTextResponse
import hmac
import hashlib
import json

from src.database.redis.connection.redis_connection import RedisConnectionHandle

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
        WEBHOOK_SECRET = "umSegredoForteAqui123"  # ideal: colocar em .env

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
            return {"error": "Invalid signature"}

        # 🔄 Caso seja o challenge (verificação inicial)
        if twitch_message_type == "webhook_callback_verification":
            data = await request.json()
            # retorna apenas o texto do challenge, conforme exigido pelo Twitch
            return PlainTextResponse(data["challenge"])

        # 📩 Evento normal (mensagem de chat)
        if twitch_message_type == "notification":
            data = await request.json()
            event = data["event"]
            # Aqui você pode salvar no Redis ou processar conforme seu fluxo
            print(f"[Chat] {event['chatter_user_name']}: {event['message']}\n")
            print(f"[Chat] {event}")
            # Exemplo de salvar no Redis
            #self.redis_conn.set(f"twitch:chat:{event['id']}", json.dumps(event))

        return {"status": "ok"}


def twitch_event_sub_routes():
    controller = TwitchEventSubController()
    return controller.router
