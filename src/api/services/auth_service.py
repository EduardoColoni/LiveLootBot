import requests

from src.core.config import twitch
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

    def generate_app_access_token(self):
        """
        Gera um App Access Token novo e grava no banco.

        É client_credentials: usa só o CLIENT_ID e o CLIENT_SECRET do app, então
        não depende de ninguém autorizar nada no navegador.
        """
        try:
            data = {
                "client_id": twitch["CLIENT_ID"],
                "client_secret": twitch["CLIENT_SECRET"],
                "grant_type": "client_credentials",
            }

            response = requests.post(f"{twitch['TWITCH_URL']}/token", data=data, timeout=10)
            response.raise_for_status()

            token_json = response.json()
            if "access_token" not in token_json:
                raise RuntimeError(f"A Twitch não devolveu um access_token: {token_json}")

            self.repo_auth.insert_app_access_token(token_json)
            print("App Access Token gerado e salvo.")
            return token_json

        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Erro na requisição do App Access Token: {str(e)}")

    def get_app_access_token(self):
        """
        Devolve um App Access Token válido, gerando outro sozinho se estiver
        faltando ou perto de vencer.

        Só vale para este token. Os tokens do streamer e do bot são de usuário:
        a Twitch só os emite depois de alguém autorizar no navegador, então
        esses não têm como ser gerados automaticamente — no máximo renovados
        pelo twitch_refresh_token abaixo.
        """
        token_data = self.repo_auth.select_valid_app_access_token()

        if token_data and "access_token" in token_data:
            return token_data

        print("App Access Token ausente ou vencido, gerando um novo...")
        return self.generate_app_access_token()

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
