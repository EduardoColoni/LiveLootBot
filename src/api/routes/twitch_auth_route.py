from fastapi import Request, APIRouter, HTTPException
import requests
import urllib.parse
import json, base64

from src.core.config import twitch
from src.core.config import api_config
from src.database.postgres.postgres_repository_auth import PostgresRepositoryAuth
from src.database.postgres.connection.postgres_connection import PostgresPool
from src.database.redis.redis_repository import RedisRepository
from src.database.redis.connection.redis_connection import RedisConnectionHandle
from starlette.responses import HTMLResponse
from datetime import datetime


class TwitchAuthController:
    def __init__(self):
        self.redis_conn = RedisConnectionHandle().connect()
        self.router = APIRouter()
        self.router.add_api_route("/twitch_callback/streamer", self.twitch_callback_streamer, methods=["GET"])
        self.router.add_api_route("/twitch_callback/viewer", self.twitch_callback_viewer, methods=["GET"])
        self.router.add_api_route("/twitch_callback/twitch_app_access_token", self.twitch_app_access_token, methods=["GET"])
        self.router.add_api_route("/twitch_callback/event_sub_signature", self.event_sub_signature, methods=["GET"])

    async def twitch_callback_streamer(self, request: Request):
        conn = PostgresPool.get_conn()
        encoded_state = request.query_params.get("state")
        try:
            repo_auth = PostgresRepositoryAuth(conn)
            code = request.query_params.get("code")

            state_json = base64.b64decode(urllib.parse.unquote(encoded_state)).decode()
            state_dict = json.loads(state_json)
            guild_id = state_dict["guild_id"]
            uuid_state = state_dict["csrf"]

            if not code or not uuid_state:
                return HTMLResponse("<h1>Erro: parâmetro ausente.</h1>", status_code=400)

            print(f"Só um teste para ver o guild_id: {guild_id}")

            data = {
                "client_id": twitch["CLIENT_ID"],
                "client_secret": twitch["CLIENT_SECRET"],
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": twitch["REDIRECT_URI_STREAMER"]
            }

            response = requests.post(twitch["TWITCH_URL"] + "/token", data=data, timeout=10)

            if response.status_code == 200:
                token_json = response.json()
                streamer_name, platform_id, display_name = self.get_user(token_json["access_token"])
                streamer_id_auth = repo_auth.select_streamer_id(guild_id)

                #Se não tiver ninguem cadastrado com o guild_id vai deixar ir, caso não vai barrar
                if streamer_id_auth is None:
                    repo_auth.new_insert_token(token_json, guild_id, streamer_name, platform_id, "twitch")
                    print("Autenticação concluída com sucesso!")
                    return HTMLResponse("<h1>Autenticação concluída com sucesso! 🎉</h1>")
                else:
                    return HTMLResponse("<h1>Apenas um streamer pode ser cadastrado por servidor ou streamer já autenticado, caso precise de ajuda entre em contato com o suporte!</h1>")

        except ValueError:
            return HTMLResponse("<h1>State malformado.</h1>", status_code=400)
        except requests.exceptions.RequestException as e:
            return HTMLResponse(f"<h1>Erro de requisição: {str(e)}</h1>", status_code=500)
        finally:
            PostgresPool.release_conn(conn)

    async def twitch_callback_viewer(self, request: Request):
        conn = PostgresPool.get_conn()
        encoded_state = request.query_params.get("state")
        try:
            repo_auth = PostgresRepositoryAuth(conn)
            code = request.query_params.get("code")

            if not code or not encoded_state:
                return HTMLResponse("<h1>Erro: parâmetro ausente.</h1>", status_code=400)

            state_json = base64.b64decode(urllib.parse.unquote(encoded_state)).decode()
            state_dict = json.loads(state_json)
            guild_id = state_dict["guild_id"]
            discord_user_id = state_dict["discord_user_id"]
            discord_user_name = state_dict["discord_user_name"]

            print(f"Só um teste para ver o guild_id: {guild_id}, e tambem o user_id: {discord_user_id} e {discord_user_name}")

            data = {
                "client_id": twitch["CLIENT_ID"],
                "client_secret": twitch["CLIENT_SECRET"],
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": twitch["REDIRECT_URI_STREAMER"]
            }

            response = requests.post(twitch["TWITCH_URL"] + "/token", data=data, timeout=10)

            if response.status_code == 200:
                token_json = response.json()
                twitch_user, twitch_id, twitch_user_name = self.get_user(token_json["access_token"])
                print(f"\nteste2 bbbbbbb {twitch_user_name} e {twitch_id}\n")
                streamer_id = repo_auth.select_streamer_id(guild_id)

                if streamer_id is None:
                    return HTMLResponse(f"Erro ao autenticar: Nenhum streamer autenticado nesse servidor", status_code=response.status_code)

                streamer_id = int(streamer_id)

                repo_auth.insert_user(streamer_id, discord_user_id, twitch_id, discord_user_name, twitch_user_name) #Vou mudar essa daqui, antes disso vou precisar fazer uma consulta para pegar o id do streamer com o guild_id
                print("Autenticação concluída com sucesso!")
                return HTMLResponse("<h1>Autenticação concluída com sucesso! 🎉</h1>")

            return HTMLResponse(f"Erro ao autenticar: {response.text}", status_code=response.status_code)

        except ValueError:
            return HTMLResponse("<h1>State malformado.</h1>", status_code=400)
        except requests.exceptions.RequestException as e:
            return HTMLResponse(f"<h1>Erro de requisição: {str(e)}</h1>", status_code=500)
        finally:
            PostgresPool.release_conn(conn)

    @staticmethod
    def get_user(token: str):
        headers = {
            "Authorization": f"Bearer {token}",
            "Client-Id": twitch["CLIENT_ID"]
        }

        #Eu busco as informações do usuário com o token dele que recebo da auth
        response = requests.get("https://api.twitch.tv/helix/users", headers=headers, timeout=10)
        response.raise_for_status()

        data = response.json()
        user = data["data"][0]
        print(f"\nteste aaaaaaaaaaa {user}\n")
        return user["login"], user["id"], user["display_name"]

    @staticmethod
    async def twitch_app_access_token():
        conn = PostgresPool.get_conn()
        repo_auth = PostgresRepositoryAuth(conn)

        try:
            data = {
                "client_id": twitch["CLIENT_ID"],
                "client_secret": twitch["CLIENT_SECRET"],
                "grant_type": "client_credentials",
            }

            # Faz a requisição à Twitch
            try:
                response = requests.post(
                    f"{twitch['TWITCH_URL']}/token",
                    data=data,
                    timeout=10
                )
            except requests.exceptions.RequestException as e:
                raise HTTPException(status_code=500, detail=f"Erro ao conectar na Twitch: {e}")

            # Checa o status da resposta
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Twitch retornou erro: {response.text}"
                )

            token_json = response.json()

            # Valida se o token veio corretamente
            if "access_token" not in token_json:
                raise HTTPException(
                    status_code=500,
                    detail=f"Twitch não retornou um access_token válido: {token_json}"
                )

            # Insere/atualiza no banco
            repo_auth.insert_app_access_token(token_json)

            return {"status": "ok", "access_token": token_json["access_token"]}

        finally:
            PostgresPool.release_conn(conn)

    @staticmethod
    async def event_sub_signature(platform_id : str):
        conn = PostgresPool.get_conn()
        try:
            repo_auth = PostgresRepositoryAuth(conn)
            url_base = api_config["URL_BASE"]

            # Obtém o App Access Token
            ################################Obviamente aqui foi preguiça minha e preciso mudar isso########################################
            app_access_token = repo_auth.select_app_access_token()
            if not app_access_token:
                raise RuntimeError("App Access Token não encontrado no banco.")

            # IDs do broadcaster e do bot
            #platform_id = "102089057"

            user_id_bot = "1355737213"

            headers = {
                "Authorization": f"Bearer {app_access_token['access_token']}",
                "Client-Id": twitch["CLIENT_ID"],
                "Content-Type": "application/json"
            }

            body = {
                "type": "channel.chat.message",
                "version": "1",
                "condition": {
                    "broadcaster_user_id": platform_id,
                    "user_id": user_id_bot
                },
                "transport": {
                    "method": "webhook",
                    "callback": f"{url_base}/twitch/eventsub",
                    "secret": "umSegredoForteAqui123"
                }
            }

            response = requests.post(
                "https://api.twitch.tv/helix/eventsub/subscriptions",
                headers=headers,
                json=body
            )

            if response.status_code != 202:
                raise RuntimeError(f"Erro ao criar EventSub subscription: {response.status_code} - {response.text}")

            sub = response.json()["data"][0]

            print(response.status_code, response.text)
            print(f"teste: {response.status_code} e tambem o: {response.text}")

            # Mapeamento de status da Twitch para o banco
            status_map = {
                "webhook_callback_verification_pending": "pending",
                "enabled": "enabled",
                "disabled": "disabled",
                "expired": "expired"
            }
            status_db = status_map.get(sub["status"], "pending")

            # Expira_at: nem sempre existe, usar created_at se necessário
            expires_at = sub.get("expires_at", sub["created_at"])
            streamer_id = repo_auth.select_streamer_id_by_platform_id(platform_id)
            # Insere no banco
            repo_auth.insert_eventsub_subscription(
                streamer_id=int(streamer_id),
                platform_id=str(platform_id),
                subscription_id=sub["id"],
                status=status_db,
                type_=sub["type"],
                transport_callback=sub["transport"]["callback"],
                webhook_secret="umSegredoForteAqui123",
                expires_at=str(datetime.fromisoformat(expires_at.replace("Z", "+00:00")))
            )

            print(f"[INFO] EventSub subscription criada com sucesso: {sub['id']}")

        finally:
            PostgresPool.release_conn(conn)


def setup_auth_routes():
    controller = TwitchAuthController()
    return controller.router
