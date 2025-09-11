from fastapi import Request, APIRouter, HTTPException
from fastapi.responses import HTMLResponse
import requests
import urllib.parse
import json, base64

from src.api.services.auth_service import AuthService
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
        self.router.add_api_route("/kick_callback/event_sub_signature", self.kick_event_sub_signature, methods=["GET"])

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

    @staticmethod
    def kick_get_user(token: str):
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

    @staticmethod
    async def kick_event_sub_signature(platform_id: str):
        conn = PostgresPool.get_conn()
        repo_auth = PostgresRepositoryAuth(conn)
        service = AuthService(conn, platform_id)

        def load_headers():
            print(f"Buscando token para a plataforma: {platform_id}")
            token_data = repo_auth.select_token_by_platform(platform_id)
            print(f"Dados brutos do token: {token_data}")
            if not token_data or "access_token" not in token_data:
                raise RuntimeError("Token de acesso não encontrado")

            access_token = token_data['access_token']
            print(f"Token de acesso a ser usado: {access_token}")
            return {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }

        def send_subscription_request(headers):
            body = {
                "broadcaster_user_id": int(platform_id),
                "events": [
                    {
                        "name": "chat.message.sent",
                        "version": 1
                    }
                ],
                "method": "webhook"
            }
            response = requests.post(
                "https://api.kick.com/public/v1/events/subscriptions",
                headers=headers,
                json=body
            )
            print(f"\nteste: {response}\n")
            print(f"\nteste: {response.json()}\n")

            response.raise_for_status()
            return response.json()

        try:
            headers = load_headers()
            subscription_data = send_subscription_request(headers)

            repo_auth.kick_insert_or_update_subscription(platform_id, subscription_data['data'][0]['subscription_id'])

            print(f"[INFO] Inscrição criada com sucesso: {subscription_data['data'][0]['subscription_id']}")
            return {"status": "ok", "subscription_id": subscription_data['data'][0]['subscription_id']}

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                print(f"Erro 401. Token inválido. Tentando refresh para platform_id={platform_id}")

                # Chama a função de refresh diretamente e lida com o retorno
                refresh_resp = service.kick_refresh_token()
                print(f"Resposta da tentativa de refresh: {refresh_resp.get('status')} - {refresh_resp.get('message')}")

                if refresh_resp.get("status") != "ok":
                    raise HTTPException(status_code=500,
                                        detail=f"Falha ao renovar token: {refresh_resp.get('message')}")

                try:
                    print("Iniciando segunda tentativa de inscrição com o novo token...")
                    headers = load_headers()
                    subscription_data = send_subscription_request(headers)

                    print("Token atualizado e inscrição feita com sucesso!")
                    return {"status": "ok", "subscription_id": subscription_data['data'][0]['subscription_id']}

                except requests.exceptions.HTTPError as e_retry:
                    raise HTTPException(status_code=500, detail=f"Erro na segunda tentativa: {e_retry.response.text}")
            else:
                raise HTTPException(status_code=500, detail=f"Erro ao criar inscrição: {e.response.text}")
        finally:
            PostgresPool.release_conn(conn)

def kick_setup_auth_routes():
    controller = KickAuthController()
    return controller.router