from aiohttp import streamer
from fastapi import Request, APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
import requests
import urllib.parse
import json, base64

from src.core.config import kick
from src.database.postgres.postgres_repository_auth import PostgresRepositoryAuth
from src.database.postgres.connection.postgres_connection import PostgresPool
from src.database.redis.redis_repository import RedisRepository
from src.database.redis.connection.redis_connection import RedisConnectionHandle


KICK_API_URL = "https://api.kick.com/api/v1"
KICK_EVENT_SUBSCRIPTION_URL = "https://api.kick.com/public/v1/events/subscriptions"
KICK_PUBLIC_KEY_URL = "https://api.kick.com/public/v1/public-key"
CLIENT_ID = "seu_client_id_kick"
CLIENT_SECRET = "seu_client_secret_kick"

class KickAuthController:
    def __init__(self):
        self.redis_conn = RedisConnectionHandle().connect()
        self.router = APIRouter()
        self.router.add_api_route("/kick_callback/streamer", self.kick_callback_streamer, methods=["GET"])
        self.router.add_api_route("/kick_callback/viewer", self.kick_callback_viewer, methods=["GET"])
        self.router.add_api_route("/kick_callback/refreshToken", self.kick_refresh_token, methods=["GET"])

    async def kick_callback_streamer(self, request: Request):
        conn = PostgresPool.get_conn()
        redis_repo = RedisRepository(self.redis_conn)
        encoded_state = request.query_params.get("state")

        try:
            repo_auth = PostgresRepositoryAuth(conn)
            code = request.query_params.get("code")
            if not code or not encoded_state:
                return HTMLResponse("<h1>Erro: parâmetro ausente.</h1>", status_code=400)

            state_json = base64.b64decode(urllib.parse.unquote(encoded_state)).decode()
            state_dict = json.loads(state_json)
            guild_id = state_dict["guild_id"]
            uuid_state = state_dict["csrf"]

            # Agora, usa o csrf para buscar o code_verifier no Redis
            code_verifier = redis_repo.get(f"oauth_state:{uuid_state}")

            print(f"teste: {guild_id}")

            if not code_verifier:
                return HTMLResponse("<h1>State inválido ou expirado.</h1>", status_code=403)

            redis_repo.delete(f"oauth_state:{uuid_state}")

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
                return HTMLResponse("<h1>Autenticação concluída com sucesso! 🎉</h1>")

            return HTMLResponse(f"Erro ao autenticar: {response.text}", status_code=response.status_code)
        except ValueError:
            return HTMLResponse("<h1>State malformado.</h1>", status_code=400)
        except requests.exceptions.RequestException as e:
            return HTMLResponse(f"<h1>Erro de requisição: {str(e)}</h1>", status_code=500)
        finally:
            PostgresPool.release_conn(conn)

    async def kick_callback_viewer(self, request: Request):
        conn = PostgresPool.get_conn()
        repo_auth = PostgresRepositoryAuth(conn)
        redis_repo = RedisRepository(self.redis_conn)
        encoded_state = request.query_params.get("state")

        try:
            code = request.query_params.get("code")
            if not code or not encoded_state:
                return HTMLResponse("<h1>Erro: parâmetro ausente.</h1>", status_code=400)

            state_json = base64.b64decode(urllib.parse.unquote(encoded_state)).decode()
            state_dict = json.loads(state_json)
            guild_id = state_dict["guild_id"]
            discord_user_id = state_dict["discord_user_id"]
            discord_user_name = state_dict["discord_user_name"]
            uuid_state = state_dict["csrf"]

            # Agora, usa o csrf para buscar o code_verifier no Redis
            code_verifier = redis_repo.get(f"oauth_state:{uuid_state}")

            print(f"Só um teste para ver o guild_id: {guild_id}, e tambem o user_id: {discord_user_id} e {discord_user_name}")

            if not code_verifier:
                return HTMLResponse("<h1>State inválido ou expirado.</h1>", status_code=403)

            redis_repo.delete(f"oauth_state:{uuid_state}")

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

#-----------------------------------------------------------------------------------------------------------------------

    async def kick_event_sub_signature(self, platform_id: str):
        """
        Cria uma nova inscrição para webhooks na Kick.
        """

        conn = PostgresPool.get_conn()
        repo_auth = PostgresRepositoryAuth(conn)

        try:

            params_refresh = {"platform_id": platform_id}

            def load_headers():
                token_data = repo_auth.select_token_by_platform(platform_id)
                if not token_data or "access_token" not in token_data:
                    raise RuntimeError("Token de acesso não encontrado")
                return {
                "Authorization": f"Bearer {token_data['access_token']}",
                "Content-Type": "application/json"
                }

            body = {
                "broadcaster_user_id": platform_id,
                "events": [
                    {
                        "name": "chat.message.sent",
                        "version": 1
                    }
                ],
                "method": "webhook",
                "callback": "https://remarkably-knowing-serval.ngrok-free.app/kick/eventsub"
            }

            def do_send_message(headers):
                response = requests.post(
                    KICK_EVENT_SUBSCRIPTION_URL,
                    headers=headers,
                    json=body
                )
                print(response.json())

                if response.status_code == 401:
                    raise RuntimeError("Token de acesso não encontrado ou inválido")

                elif response.status_code != 200:
                    raise RuntimeError(f"Erro ao fazer a inscrição: {response.status_code} - {response.text}")

                print("Mensagem enviada com sucesso")
                return JSONResponse(content=response.json())

            try:
                headers = load_headers()
                return do_send_message(headers)
            except RuntimeError as e:
                if "Token de acesso não encontrado" in str(e):
                    print(f"[INFO] Token inválido. Tentando refresh para platform_id={platform_id}")
                    refresh_resp = requests.get(f"{url_base}/twitch_callback/get_refreshToken", params=params_refresh)
                    if refresh_resp.status_code != 200:
                        raise RuntimeError(f"Falha ao renovar token: {refresh_resp.status_code} - {refresh_resp.text}")

                    #recarrega token atualizado e tenta novamente
                    headers = load_headers()
                    print("\ntoken atualizado!")
                    return do_send_message(headers)
                else:
                    raise
            sub = response.json()["data"][0]

            # AQUI: Lógica para salvar os detalhes da inscrição no banco de dados.
            # O ID da inscrição e o status são importantes para o gerenciamento.
            # Campos para salvar:
            # - subscription_id: sub["subscription_id"]
            # - broadcaster_id: broadcaster_id
            # - event_type: sub["name"]
            # - status: 'enabled' (ou outro status retornado)

            print(f"[INFO] Inscrição em evento da Kick criada com sucesso: {sub['subscription_id']}")
            print(f"\nSó quero saber o que chegou; {response}")
            return {"status": "ok", "subscription_id": sub["subscription_id"]}

        except requests.exceptions.HTTPError as e:
            print(f"Erro ao criar inscrição: {e.response.status_code} - {e.response.text}")
            raise HTTPException(status_code=500, detail=f"Erro ao criar inscrição na Kick: {e.response.text}")
        finally:
            PostgresPool.release_conn(conn)

def kick_setup_auth_routes():
    controller = KickAuthController()
    return controller.router