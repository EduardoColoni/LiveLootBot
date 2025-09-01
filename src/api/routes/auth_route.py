from fastapi import Request, APIRouter
from fastapi.responses import HTMLResponse
import requests
import urllib.parse

from src.core.config import twitch
from src.database.postgres.postgres_repository_auth import PostgresRepositoryAuth
from src.database.postgres.connection.postgres_connection import PostgresPool
from src.database.redis.redis_repository import RedisRepository
from src.database.redis.connection.redis_connection import RedisConnectionHandle
from starlette.responses import HTMLResponse, RedirectResponse


class TwitchAuthController:
    def __init__(self):
        self.redis_conn = RedisConnectionHandle().connect()
        self.router = APIRouter()
        self.router.add_api_route("/twitch_callback/streamer", self.twitch_callback_streamer, methods=["GET"])
        self.router.add_api_route("/twitch_callback/viewer", self.twitch_callback_viewer, methods=["GET"])
        self.router.add_api_route("/get_refreshToken", self.refresh_token, methods=["GET"])

    async def twitch_callback_streamer(self, request: Request):
        conn = PostgresPool.get_conn()
        encoded_state = request.query_params.get("state")
        try:
            repo_auth = PostgresRepositoryAuth(conn)
            code = request.query_params.get("code")

            if not code or not encoded_state:
                return HTMLResponse("<h1>Erro: parâmetro ausente.</h1>", status_code=400)

            state = urllib.parse.unquote(encoded_state)

            print(f"Só quero ver o que ta chegando: {state}")

            try:
                guild_id, uuid_state = state.split(":")
            except ValueError:
                return HTMLResponse("<h1>Erro: Formato de state inválido.</h1>", status_code=400)

            print(f"Só um teste para ver o guild_id: {guild_id}")

            data = {
                "client_id": "qamgu47p8wl6qio8fa2ef3e37q3eu2",
                "client_secret": twitch["CLIENT_SECRET"],
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": twitch["REDIRECT_URI"]
            }

            response = requests.post(twitch["TWITCH_URL"] + "/token", data=data, timeout=10)

            if response.status_code == 200:
                token_json = response.json()
                streamer_name, platform_id = self.get_user(token_json["access_token"])
                repo_auth.new_insert_token(token_json, guild_id, streamer_name, platform_id, "twitch")
                print("Autenticação concluída com sucesso!")
                return HTMLResponse("<h1>Autenticação concluída com sucesso! 🎉</h1>")

            return HTMLResponse(f"Erro ao autenticar: {response.text}", status_code=response.status_code)

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

            state = urllib.parse.unquote(encoded_state)

            try:
                guild_id, discord_user_id, discord_user_name, uuid_state = state.split(":") #essa daqui vou mudar quero o id do discord do usuário também
            except ValueError:
                return HTMLResponse("<h1>Erro: Formato de state inválido.</h1>", status_code=400)

            print(f"Só um teste para ver o guild_id: {guild_id}, e tambem o user_id: {discord_user_id} e {discord_user_name}")

            data = {
                "client_id": "qamgu47p8wl6qio8fa2ef3e37q3eu2",
                "client_secret": twitch["CLIENT_SECRET"],
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": twitch["REDIRECT_URI"]
            }

            response = requests.post(twitch["TWITCH_URL"] + "/token", data=data, timeout=10)

            if response.status_code == 200:
                token_json = response.json()
                twitch_user_name, twitch_id = self.get_user(token_json["access_token"])
                streamer_id = int(repo_auth.select_streamer_id(guild_id))
                repo_auth.insert_user(streamer_id, discord_user_id, twitch_id, twitch_user_name, discord_user_name) #Vou mudar essa daqui, antes disso vou precisar fazer uma consulta para pegar o id do streamer com o guild_id
                print("Autenticação concluída com sucesso!")
                return HTMLResponse("<h1>Autenticação concluída com sucesso! 🎉</h1>")

            return HTMLResponse(f"Erro ao autenticar: {response.text}", status_code=response.status_code)

        except ValueError:
            return HTMLResponse("<h1>State malformado.</h1>", status_code=400)
        except requests.exceptions.RequestException as e:
            return HTMLResponse(f"<h1>Erro de requisição: {str(e)}</h1>", status_code=500)
        finally:
            PostgresPool.release_conn(conn)

    async def refresh_token(self, request: Request):
        conn = PostgresPool.get_conn()
        try:
            repo_auth = PostgresRepositoryAuth(conn)

            token_data = repo_auth.select_token()
            if not token_data:
                return HTMLResponse("<h1>Token não encontrado.</h1>", status_code=401)

            refresh_token = token_data.get("refresh_token")
            if not refresh_token:
                return HTMLResponse("<h1>Refresh token ausente.</h1>", status_code=400)

            data = {
                "client_id": twitch["CLIENT_ID"],
                "client_secret": twitch["CLIENT_SECRET"],
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                "redirect_uri": twitch["REDIRECT_URI"]
            }

            response = requests.post(f"{twitch['TWITCH_URL']}/token", data=data, timeout=10)

            if response.status_code == 200:
                token_json = response.json()
                repo_auth.refresh_token(token_json)
                print("Token atualizado com sucesso!")
                return HTMLResponse("<h1>Token atualizado com sucesso!</h1>")

            return HTMLResponse(f"Erro ao atualizar token: {response.text}", status_code=response.status_code)

        except requests.exceptions.RequestException as e:
            return HTMLResponse(f"<h1>Erro na requisição: {str(e)}</h1>", status_code=500)
        finally:
            PostgresPool.release_conn(conn)

    def get_user(self, token: str):
        headers = {
            "Authorization": f"Bearer {token}",
            "Client-Id": twitch["CLIENT_ID"]
        }

        #Eu busco as informações do usuário com o token dele que recebo da auth
        response = requests.get("https://api.twitch.tv/helix/users", headers=headers, timeout=10)
        response.raise_for_status()

        data = response.json()
        user = data["data"][0]
        return user["login"], user["id"]


def setup_auth_routes():
    controller = TwitchAuthController()
    return controller.router
