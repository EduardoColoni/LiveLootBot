import requests

from src.core.config import twitch, kick
from src.database.redis.redis_repository import RedisRepository
from src.database.redis.connection.redis_connection import RedisConnectionHandle
from src.database.postgres.postgres_repository_auth import PostgresRepositoryAuth
from src.database.postgres.postgres_repository_raffle import PostgresRepositoryRaffle
from src.database.postgres.connection.postgres_connection import PostgresPool


class AuthService:
    def __init__(self, conn=None, platform_id=None):
        self.platform_id = str(platform_id)
        self.conn = conn
        self.repo_auth = PostgresRepositoryAuth(self.conn)
        self.redis_conn = RedisConnectionHandle().connect()

    def twitch_refresh_token(self):
        try:
            print(f"teste para ver o platform_id do refresh token twitch: {self.platform_id}")
            token_data = self.repo_auth.select_token_by_platform(self.platform_id)
            print(f"teste para ver o token do refresh token twitch:{token_data}")
            if not token_data:
                # Em vez de retornar uma resposta HTTP, levante um erro para ser tratado
                raise RuntimeError("Token não encontrado twitch.")

            print(f"teste para ver o token do refresh token twitch:{token_data}")
            refresh_token = token_data.get("refresh_token")

            print(f"teste para ver o refresh do refresh token twitch: {refresh_token}")
            if not refresh_token:
                raise RuntimeError("Refresh token ausente twitch.")

            data = {
                "client_id": twitch["CLIENT_ID"],
                "client_secret": twitch["CLIENT_SECRET"],
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                "redirect_uri": twitch["REDIRECT_URI_STREAMER"]
            }

            response = requests.post(f"{twitch['TWITCH_URL']}/token", data=data, timeout=10)
            response.raise_for_status()  # Lança exceção para status 4xx/5xx

            token_json = response.json()
            self.repo_auth.refresh_token(token_json, self.platform_id)
            print("Token atualizado com sucesso twitch!")

        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Erro na requisição para a Twitch: {str(e)}")
        except Exception as e:
            raise RuntimeError(f"Erro interno no refresh twitch: {str(e)}")

    def kick_refresh_token(self):
        try:

            token_data = self.repo_auth.select_token_by_platform(self.platform_id)
            if not token_data:
                return {"status": "error", "message": "Token não encontrado kick."}

            refresh_token = token_data.get("refresh_token")
            if not refresh_token:
                return {"status": "error", "message": "Refresh token ausente kick."}

            data = {
                "grant_type": "refresh_token",
                "client_id": kick["CLIENT_ID_KICK"],
                "client_secret": kick["CLIENT_SECRET_KICK"],
                "refresh_token": refresh_token
            }

            response = requests.post(f"{kick['KICK_URL']}/token", data=data, timeout=10)
            response.raise_for_status()

            token_json = response.json()
            self.repo_auth.refresh_token(token_json, self.platform_id)
            print("Token atualizado com sucesso! kick")
            return {"status": "ok", "message": "Token atualizado com sucesso! kick"}

        except requests.exceptions.RequestException as e:
            return {"status": "error", "message": f"Erro na requisição kick: {str(e)}"}
        except Exception as e:
            return {"status": "error", "message": f"Erro interno kick: {str(e)}"}