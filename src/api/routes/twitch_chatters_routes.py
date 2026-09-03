import requests
from fastapi import Request, APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from src.api.services.auth_service import AuthService
from src.database.postgres.postgres_repository_auth import PostgresRepositoryAuth
from src.database.postgres.connection.postgres_connection import PostgresPool
from src.core.config import twitch
from src.core.config import api_config


class TwitchChattersController:
    def __init__(self):
        self.router = APIRouter()
        # self.router.add_api_route(
        #     "/twitch_chatters/get_chatters/{streamer_id}",
        #     self.get_chatters,
        #     methods=["GET"]
        # )
        self.router.add_api_route(
            "/twitch_chatters/send_message",
            self.send_message,
            methods=["POST"]
        )

    # async def get_chatters(self, request: Request, streamer_id: str):
    #     """Endpoint para obter os chatters de um canal da Twitch"""
    #     conn = PostgresPool.get_conn()
    #     try:
    #         repo_auth = PostgresRepositoryAuth(conn)
    #
    #         token_data = repo_auth.select_token_by_streamer(streamer_id)
    #         if not token_data or "access_token" not in token_data:
    #             return HTMLResponse(
    #                 content="<h1>Token de acesso não encontrado</h1>",
    #                 status_code=401
    #             )
    #
    #         headers = {
    #             "Authorization": f"Bearer {token_data['access_token']}",
    #             "Client-Id": twitch["CLIENT_ID"]
    #         }
    #
    #         params = {
    #             "broadcaster_id": streamer_id,
    #             "moderator_id": streamer_id,
    #             "first": 1000
    #         }
    #
    #         response = requests.get(
    #             "https://api.twitch.tv/helix/chat/chatters",
    #             headers=headers,
    #             params=params,
    #             timeout=10
    #         )
    #
    #         if response.status_code == 200:
    #             print("Chatters pego com sucesso")
    #             return JSONResponse(content=response.json())
    #         return HTMLResponse(
    #             content=f"<h1>Erro na API Twitch: {response.text}</h1>",
    #             status_code=response.status_code
    #         )
    #
    #     except requests.exceptions.RequestException as e:
    #         return HTMLResponse(
    #             content=f"<h1>Erro na requisição: {str(e)}</h1>",
    #             status_code=500
    #         )
    #     finally:
    #         PostgresPool.release_conn(conn)

    async def send_message(self, platform_id: str, user_name: str, item_name: str, message_control: str):
        conn = PostgresPool.get_conn()

        print(f"Esse é o conteudo do platform_id dentro da função da api {platform_id}")
        try:
            repo_auth = PostgresRepositoryAuth(conn)

            bot_platform_id = twitch["BOT_PLATFORM_ID"]
            service = AuthService(conn, bot_platform_id)

            def load_headers():
                token_data = repo_auth.select_token_by_platform(bot_platform_id)
                if not token_data or "access_token" not in token_data:
                    # Esse token só existe depois de alguém autorizar a conta do bot
                    # no navegador, então não dá para gerar aqui: avisa o que fazer.
                    raise HTTPException(
                        status_code=503,
                        detail=(
                            f"Token do bot (platform_id {bot_platform_id}) não está no banco. "
                            "Rode /autenticar_plataformas no Discord e clique em "
                            "'Autenticação do Bot', logado na Twitch com a conta do bot."
                        )
                    )
                return {
                    "Authorization": f"Bearer {token_data['access_token']}",
                    "Client-Id": twitch["CLIENT_ID"]
                }

            # Constrói o corpo da mensagem
            message_map = {
                "claim": f"🎯 @{user_name}, você foi sorteado para o item: {item_name}! Digite !claim em até 1 minuto para garantir seu prêmio! 🕹️",
                "resend_claim": f"⚠️ @{user_name} não deu !claim! O item {item_name} será sorteado novamente 🔄🎮",
                "winner": f"🏆 @{user_name} confirmou o !claim! Você ganhou o item: {item_name} 🎉✨",
                "not-claim": f"❌ Ninguém deu !claim no item {item_name} após 3 tentativas! Um novo item será sorteado 🎲🔥"
            }

            json_body = {
                "broadcaster_id": platform_id,
                "moderator_id": bot_platform_id,
                "sender_id": bot_platform_id,
                "message": message_map.get(message_control, "")
            }

            # Função para fazer a requisição de envio
            def do_send_message_request(headers):
                response = requests.post(
                    "https://api.twitch.tv/helix/chat/messages",
                    headers=headers,
                    json=json_body
                )
                response.raise_for_status()
                return response.json()

            try:
                # Primeira tentativa
                headers = load_headers()
                response_data = do_send_message_request(headers)
                print("Mensagem enviada com sucesso")
                return JSONResponse(content=response_data)

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 401:
                    print(f"[INFO] Token inválido. Tentando refresh para bot_platform_id={bot_platform_id}")

                    try:
                        # Chamada direta para a função de refresh
                        service.twitch_refresh_token()

                        # Segunda tentativa após o refresh
                        headers = load_headers()
                        response_data = do_send_message_request(headers)
                        print("Token atualizado e mensagem enviada com sucesso!")
                        return JSONResponse(content=response_data)

                    except RuntimeError as e_refresh:
                        raise HTTPException(
                            status_code=500,
                            detail=f"Falha ao renovar token e reenviar: {str(e_refresh)}"
                        )
                else:
                    raise HTTPException(
                        status_code=e.response.status_code,
                        detail=f"Erro ao enviar a mensagem: {e.response.text}"
                    )

        finally:
            PostgresPool.release_conn(conn)


def setup_chatters_routes():
    controller = TwitchChattersController()
    return controller.router
