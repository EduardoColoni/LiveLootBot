import requests
from fastapi import Request, APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from src.database.postgres.postgres_repository_auth import PostgresRepositoryAuth
from src.database.postgres.connection.postgres_connection import PostgresPool
from src.core.config import twitch
from src.core.config import api_config


class TwitchChattersController:
    def __init__(self):
        self.router = APIRouter()
        self.router.add_api_route(
            "/twitch_chatters/get_chatters/{streamer_id}",
            self.get_chatters,
            methods=["GET"]
        )
        self.router.add_api_route(
            "/twitch_chatters/send_message",
            self.send_message,
            methods=["POST"]
        )

    async def get_chatters(self, request: Request, streamer_id: str):
        """Endpoint para obter os chatters de um canal da Twitch"""
        conn = PostgresPool.get_conn()
        try:
            repo_auth = PostgresRepositoryAuth(conn)

            token_data = repo_auth.select_token_by_streamer(streamer_id)
            if not token_data or "access_token" not in token_data:
                return HTMLResponse(
                    content="<h1>Token de acesso não encontrado</h1>",
                    status_code=401
                )

            headers = {
                "Authorization": f"Bearer {token_data['access_token']}",
                "Client-Id": twitch["CLIENT_ID"]
            }

            params = {
                "broadcaster_id": streamer_id,
                "moderator_id": streamer_id,
                "first": 1000
            }

            response = requests.get(
                "https://api.twitch.tv/helix/chat/chatters",
                headers=headers,
                params=params,
                timeout=10
            )

            if response.status_code == 200:
                print("Chatters pego com sucesso")
                return JSONResponse(content=response.json())
            return HTMLResponse(
                content=f"<h1>Erro na API Twitch: {response.text}</h1>",
                status_code=response.status_code
            )

        except requests.exceptions.RequestException as e:
            return HTMLResponse(
                content=f"<h1>Erro na requisição: {str(e)}</h1>",
                status_code=500
            )
        finally:
            PostgresPool.release_conn(conn)

    async def send_message(self, request: Request, platform_id: str, user_id: str, item_name: str):
        conn = PostgresPool.get_conn()
        url_base = api_config["URL_BASE"]

        try:
            repo_auth = PostgresRepositoryAuth(conn)

            bot_platform_id = "1355737213"  # ID fixo do bot
            params_refresh = {"platform_id": bot_platform_id}

            def load_headers():
                token_data = repo_auth.select_token_by_platform(bot_platform_id)
                if not token_data or "access_token" not in token_data:
                    raise RuntimeError("Token de acesso não encontrado")
                return {
                    "Authorization": f"Bearer {token_data['access_token']}",
                    "Client-Id": twitch["CLIENT_ID"]
                }

            json_body = {
                "broadcaster_id": platform_id,  # streamer alvo
                "moderator_id": bot_platform_id,  # bot
                "sender_id": bot_platform_id,  # bot
                "message": f"Parabéns @{user_id} você foi sorteado! e ganhou o item: {item_name}"
            }

            def do_send_message(headers):
                response = requests.post(
                    "https://api.twitch.tv/helix/chat/messages",
                    headers=headers,
                    json=json_body
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
                    print(f"[INFO] Token inválido. Tentando refresh para bot_platform_id={bot_platform_id}")
                    refresh_resp = requests.get(f"{url_base}/twitch_callback/get_refreshToken", params=params_refresh)
                    if refresh_resp.status_code != 200:
                        raise RuntimeError(f"Falha ao renovar token: {refresh_resp.status_code} - {refresh_resp.text}")

                    #recarrega token atualizado e tenta novamente
                    headers = load_headers()
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


def setup_chatters_routes():
    controller = TwitchChattersController()
    return controller.router
