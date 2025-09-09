from aiohttp import streamer
from fastapi import Request, APIRouter, HTTPException
from fastapi.responses import HTMLResponse
import requests
import urllib.parse
import json, base64

from starlette.responses import JSONResponse

from src.api.services.auth_service import AuthService
from src.core.config import kick, api_config
from src.database.postgres.postgres_repository_auth import PostgresRepositoryAuth
from src.database.postgres.connection.postgres_connection import PostgresPool
from src.database.redis.redis_repository import RedisRepository
from src.database.redis.connection.redis_connection import RedisConnectionHandle

class KickChattersController:
    def __init__(self):
        self.redis_conn = RedisConnectionHandle().connect()
        self.router = APIRouter()
        self.router.add_api_route("/kick_chatters/send_message", self.kick_send_message, methods=["POST"])

    async def kick_send_message(self, platform_id: str, user_name: str, item_name: str, message_control: str):
        conn = PostgresPool.get_conn()
        url_base = api_config["URL_BASE"]
        try:
            repo_auth = PostgresRepositoryAuth(conn)
            service = AuthService(conn, platform_id)

            # Helper function to load headers
            def load_headers():
                token_data = repo_auth.select_token_by_platform(platform_id)
                if not token_data or "access_token" not in token_data:
                    raise RuntimeError("Token de acesso não encontrado")
                return {
                    "Authorization": f"Bearer {token_data['access_token']}",
                    "Content-Type": "application/json"
                }

            # Helper function to send the message request
            def do_send_message(headers):
                # Payload construction remains the same
                if message_control == "claim":
                    payload = {
                        "broadcaster_user_id": 1,
                        "content": f"🎯 @{user_name}, você foi sorteado para o item: {item_name}! Digite !claim em até 1 minuto para garantir seu prêmio! 🕹️",
                        "reply_to_message_id": "",
                        "type": "bot"
                    }
                elif message_control == "resend_claim":
                    payload = {
                        "content": f"⚠️ @{user_name} não deu !claim! O item {item_name} será sorteado novamente 🔄🎮",
                        "type": "bot"
                    }
                elif message_control == "winner":
                    payload = {
                        "content": f"🏆 @{user_name} confirmou o !claim! Você ganhou o item: {item_name} 🎉✨",
                        "type": "bot"
                    }
                else:  # "not-claim"
                    payload = {
                        "content": f"❌ Ninguém deu !claim no item {item_name} após 3 tentativas! Um novo item será sorteado 🎲🔥",
                        "type": "bot"
                    }

                response = requests.post(
                    "https://api.kick.com/public/v1/chat",
                    headers=headers,
                    data=json.dumps(payload)
                )
                response.raise_for_status()  # Raise an exception for HTTP errors
                return response.json()

            try:
                # FIRST ATTEMPT: Try to send the message with the current token
                headers = load_headers()
                response_data = do_send_message(headers)
                print("Mensagem enviada com sucesso!")
                return JSONResponse(content=response_data)

            except requests.exceptions.HTTPError as e:
                # Only try to refresh if the error is a 401 Unauthorized
                if e.response.status_code == 401:
                    print(f"[INFO] Token inválido. Tentando refresh para platform_id={platform_id}")
                    try:
                        # Refresh the token
                        service.kick_refresh_token()

                        # SECOND ATTEMPT: Try to send the message again with the new token
                        headers = load_headers()
                        response_data = do_send_message(headers)
                        print("Token atualizado e mensagem enviada com sucesso!")
                        return JSONResponse(content=response_data)

                    except RuntimeError as e_refresh:
                        raise HTTPException(
                            status_code=500,
                            detail=f"Falha ao renovar token e reenviar: {str(e_refresh)}"
                        )
                else:
                    # If it's any other error (e.g., 404, 422), raise it as an HTTPException
                    raise HTTPException(
                        status_code=e.response.status_code,
                        detail=f"Erro ao enviar a mensagem: {e.response.text}"
                    )

        except requests.exceptions.RequestException as e:
            return HTMLResponse(
                content=f"<h1>Erro na requisição: {str(e)}</h1>",
                status_code=500
            )
        finally:
            PostgresPool.release_conn(conn)



def kick_setup_chatters_routes():
    controller = KickChattersController()
    return controller.router