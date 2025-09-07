from aiohttp import streamer
from fastapi import Request, APIRouter
from fastapi.responses import HTMLResponse
import requests
import urllib.parse
import json, base64

from starlette.responses import JSONResponse

from src.core.config import kick, api_config
from src.database.postgres.postgres_repository_auth import PostgresRepositoryAuth
from src.database.postgres.connection.postgres_connection import PostgresPool
from src.database.redis.redis_repository import RedisRepository
from src.database.redis.connection.redis_connection import RedisConnectionHandle

class KickChattersController:
    def __init__(self):
        self.redis_conn = RedisConnectionHandle().connect()
        self.router = APIRouter()
        self.router.add_api_route("/kick_callback/send_message", self.kick_send_message, methods=["GET"])

    async def kick_send_message(self, request: Request, platform_id: str, user_id: str, item_name: str, message_control : str):
        conn = PostgresPool.get_conn()
        url_base = api_config["URL_BASE"]

        try:
            repo_auth = PostgresRepositoryAuth(conn)

            params_refresh = {"platform_id": platform_id}

            def load_headers():
                token_data = repo_auth.select_token_by_platform(platform_id)
                if not token_data or "access_token" not in token_data:
                    raise RuntimeError("Token de acesso não encontrado")
                return {
                    "Authorization": f"Bearer {token_data['access_token']}",
                    "Content-Type" : "application/json"
                }

            if message_control == "claim":
                payload = {
                    "broadcaster_user_id": 1,
                    "content": f"🎯 @{user_id}, você foi sorteado para o item: {item_name}! Digite !claim em até 1 minuto para garantir seu prêmio! 🕹️",
                    "reply_to_message_id": "",
                    "type": "bot"
                }
            elif message_control == "resend_claim":
                payload = {
                    "content": f"⚠️ @{user_id} não deu !claim! O item {item_name} será sorteado novamente 🔄🎮",
                    "type": "bot"
                }
            elif message_control == "winner":
                payload = {
                    "content": f"🏆 @{user_id} confirmou o !claim! Você ganhou o item: {item_name} 🎉✨",
                    "type": "bot"
                }
            elif message_control == "not-claim":
                payload = {
                    "content": f"❌ Ninguém deu !claim no item {item_name} após 3 tentativas! Um novo item será sorteado 🎲🔥",
                    "type": "bot"
                }

            def do_send_message(headers):
                response = requests.post(
                    "https://api.kick.com/public/v1/chat",
                    headers=headers,
                    data=json.dumps(payload)
                )
                print(response.json())

                if response.status_code == 401:
                    raise RuntimeError("Token de acesso não encontrado ou inválido")
                elif response.status_code != 200:
                    raise RuntimeError(f"Erro ao enviar a mensagem: {response.status_code} - {response.text}")

                print("Mensagem enviada com sucesso")
                return JSONResponse(content=response.json())

            try:
                headers = load_headers()
                return do_send_message(headers)
            except RuntimeError as e:
                if "Token de acesso não encontrado" in str(e):
                    print(f"[INFO] Token inválido. Tentando refresh para kick_platform_id={platform_id}")
                    refresh_resp = requests.get(f"{url_base}/kick_callback/refreshToken", params=params_refresh)
                    if refresh_resp.status_code != 200:
                        raise RuntimeError(f"Falha ao renovar token: {refresh_resp.status_code} - {refresh_resp.text}")

                    #recarrega token atualizado e tenta novamente
                    headers = load_headers()
                    print("\ntoken atualizado!")
                    return do_send_message(headers)
                else:
                    raise

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