from aiohttp import streamer
from fastapi import Request, APIRouter
from fastapi.responses import HTMLResponse
import requests
import urllib.parse

from src.core.config import kick
from src.database.postgres.postgres_repository_auth import PostgresRepositoryAuth
from src.database.postgres.connection.postgres_connection import PostgresPool
from src.database.redis.redis_repository import RedisRepository
from src.database.redis.connection.redis_connection import RedisConnectionHandle

class KickAuthController:
    def __init__(self):
        self.redis_conn = RedisConnectionHandle().connect()
        self.router = APIRouter()
        self.router.add_api_route("/kick_callback/streamer", self.kick_callback_streamer, methods=["GET"])
        self.router.add_api_route("/kick_callback/viewer", self.kick_callback_viewer, methods=["GET"])
        self.router.add_api_route("/kick_get_refreshToken", self.kick_refresh_token, methods=["GET"])

    async def kick_callback_streamer(self, request: Request):
        conn = PostgresPool.get_conn()
        redis_repo = RedisRepository(self.redis_conn)
        encoded_state = request.query_params.get("state")

        try:
            repo_auth = PostgresRepositoryAuth(conn)
            code = request.query_params.get("code")
            if not code or not encoded_state:
                return HTMLResponse("<h1>Erro: parâmetro ausente.</h1>", status_code=400)

            # Decodifica o state e extrai apenas o csrf
            state = urllib.parse.unquote(encoded_state)
            try:
                # Pega apenas o segundo valor após o ":"
                guild_id, csrf = state.split(":")
            except ValueError:
                return HTMLResponse("<h1>Erro: Formato de state inválido.</h1>", status_code=400)

            # Agora, usa o csrf para buscar o code_verifier no Redis
            code_verifier = redis_repo.get(f"oauth_state:{csrf}")

            print(f"teste: {guild_id}")

            if not code_verifier:
                return HTMLResponse("<h1>State inválido ou expirado.</h1>", status_code=403)

            redis_repo.delete(f"oauth_state:{csrf}")

            data = {
                "client_id": kick["CLIENT_ID_KICK"],
                "client_secret": kick["CLIENT_SECRET_KICK"],
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": kick["REDIRECT_URI_STREAMER_KICK"],
                "code_verifier": code_verifier
            }

            response = requests.post(kick["KICK_URL"] + "/token", data=data, timeout=10)

            if response.status_code == 200:
                token_json = response.json()
                streamer_name, platform_id = self.kick_get_user(token_json["access_token"])
                repo_auth.new_insert_token(token_json, guild_id, streamer_name, platform_id, "kick")
                print(response.json())
                return HTMLResponse("Deu certo")

            return HTMLResponse(f"Erro ao autenticar: {response.text}", status_code=response.status_code)
        except ValueError:
            return HTMLResponse("<h1>State malformado.</h1>", status_code=400)
        except requests.exceptions.RequestException as e:
            return HTMLResponse(f"<h1>Erro de requisição: {str(e)}</h1>", status_code=500)
        finally:
            PostgresPool.release_conn(conn)

    async def kick_callback_viewer(self, request: Request):
        conn = PostgresPool.get_conn()
        redis_repo = RedisRepository(self.redis_conn)
        encoded_state = request.query_params.get("state")

        try:
            repo_auth = PostgresRepositoryAuth(conn)
            code = request.query_params.get("code")
            if not code or not encoded_state:
                return HTMLResponse("<h1>Erro: parâmetro ausente.</h1>", status_code=400)

            # Decodifica o state e extrai apenas o csrf
            state = urllib.parse.unquote(encoded_state)
            try:
                # Pega apenas o segundo valor após o ":"
                guild_id, discord_user_id, discord_user_name, csrf = state.split(":")
            except ValueError:
                return HTMLResponse("<h1>Erro: Formato de state inválido.</h1>", status_code=400)

            # Agora, usa o csrf para buscar o code_verifier no Redis
            code_verifier = redis_repo.get(f"oauth_state:{csrf}")

            print(f"Só um teste para ver o guild_id: {guild_id}, e tambem o user_id: {discord_user_id} e {discord_user_name}")

            if not code_verifier:
                return HTMLResponse("<h1>State inválido ou expirado.</h1>", status_code=403)

            redis_repo.delete(f"oauth_state:{csrf}")

            data = {
                "client_id": kick["CLIENT_ID_KICK"],
                "client_secret": kick["CLIENT_SECRET_KICK"],
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": kick["REDIRECT_URI_VIEWER_KICK"],
                "code_verifier": code_verifier
            }

            response = requests.post("https://id.kick.com/oauth/token", data=data, timeout=10)

            if response.status_code == 200:
                token_json = response.json()
                streamer_name, platform_id = self.kick_get_user(token_json["access_token"])
                streamer_id = int(repo_auth.select_streamer_id(guild_id))
                repo_auth.insert_user(streamer_id, discord_user_id, None, platform_id, discord_user_name, None, streamer_name)
                print(response.json())
                return HTMLResponse("<h1>Autenticação concluída com sucesso! 🎉</h1>")

            return HTMLResponse(f"Erro ao autenticar: {response.text}", status_code=response.status_code)
        except ValueError:
            return HTMLResponse("<h1>State malformado.</h1>", status_code=400)
        except requests.exceptions.RequestException as e:
            return HTMLResponse(f"<h1>Erro de requisição: {str(e)}</h1>", status_code=500)
        finally:
            PostgresPool.release_conn(conn)

    async def kick_refresh_token(self, request: Request):
        print("a")

    def kick_get_user(self, token: str):
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "*/*"
        }

        response = requests.get("https://api.kick.com/public/v1/users", headers=headers)
        response.raise_for_status()

        data = response.json()
        if not data.get("data"):
            raise ValueError("Nenhum usuário retornado pela Kick")

        user = data["data"][0]
        print(f"\nteste aaaaaaaaaaa {user}\n")
        return user["name"], user["user_id"]

def kick_setup_auth_routes():
    controller = KickAuthController()
    return controller.router