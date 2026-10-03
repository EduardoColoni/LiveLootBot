from fastapi import Request, APIRouter, HTTPException
import requests
import urllib.parse
import json, base64

from src.api.services.auth_service import AuthService
from src.core.config import twitch
from src.core.config import api_config
from src.core.criptografia import get_webhook_secret, impressao_digital_segredo
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
        self.router.add_api_route("/twitch_callback/bot", self.twitch_callback_bot, methods=["GET"])
        self.router.add_api_route("/twitch_callback/twitch_app_access_token", self.twitch_app_access_token, methods=["GET"])
        self.router.add_api_route("/twitch_callback/event_sub_signature", self.event_sub_signature, methods=["GET"])

    def twitch_callback_streamer(self, request: Request):
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

    def twitch_callback_bot(self, request: Request):
        """
        Callback da autorização da conta do BOT.

        Diferente do callback do streamer, aqui não se cria nem se atualiza nada
        na tabela streamer: o bot não é um streamer, é a conta que fala no chat.
        O token vai para streamer_platform com platform_name 'twitch_bot'.
        """
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

            data = {
                "client_id": twitch["CLIENT_ID"],
                "client_secret": twitch["CLIENT_SECRET"],
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": twitch["REDIRECT_URI_BOT"]
            }

            response = requests.post(twitch["TWITCH_URL"] + "/token", data=data, timeout=10)

            if response.status_code != 200:
                return HTMLResponse(f"Erro ao autenticar: {response.text}", status_code=response.status_code)

            token_json = response.json()
            bot_login, bot_platform_id, bot_display_name = self.get_user(token_json["access_token"])

            # O resto do código busca o token do bot por esse id fixo, então
            # autorizar com a conta errada gravaria um token que ninguém acha.
            if str(bot_platform_id) != str(twitch["BOT_PLATFORM_ID"]):
                return HTMLResponse(
                    f"<h1>Conta errada</h1>"
                    f"<p>Você autorizou com a conta <b>{bot_display_name}</b> (id {bot_platform_id}), "
                    f"mas o bot configurado é o id <b>{twitch['BOT_PLATFORM_ID']}</b>.</p>"
                    f"<p>Saia da Twitch, entre com a conta do bot e tente de novo.</p>",
                    status_code=400
                )

            streamer_id = repo_auth.select_streamer_id(guild_id)
            if streamer_id is None:
                return HTMLResponse(
                    "<h1>Nenhum streamer autenticado nesse servidor. Autentique o streamer primeiro.</h1>",
                    status_code=400
                )

            repo_auth.insert_bot_token(token_json, int(streamer_id), str(bot_platform_id))
            print(f"Token do bot ({bot_display_name}) salvo com sucesso!")
            return HTMLResponse("<h1>Bot autenticado com sucesso! 🤖</h1>")

        except ValueError:
            return HTMLResponse("<h1>State malformado.</h1>", status_code=400)
        except requests.exceptions.RequestException as e:
            return HTMLResponse(f"<h1>Erro de requisição: {str(e)}</h1>", status_code=500)
        finally:
            PostgresPool.release_conn(conn)

    def twitch_callback_viewer(self, request: Request):
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
    def twitch_app_access_token():
        """
        Força a geração de um App Access Token novo.

        Continua existindo para uso manual, mas não é mais obrigatório chamar
        antes do event_sub_signature: ele já gera sozinho quando precisa.
        """
        conn = PostgresPool.get_conn()
        try:
            token_json = AuthService(conn).generate_app_access_token()
            return {"status": "ok", "access_token": token_json["access_token"]}

        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            PostgresPool.release_conn(conn)

    @staticmethod
    def find_eventsub_subscription(headers: dict, broadcaster_id: str, user_id_bot: str):
        """
        Procura na Twitch a inscrição de chat desse canal com esse bot.

        Serve para quando a Twitch responde 409 (já existe): o banco é que está
        fora de sincronia, e aí dá para gravar a que já existe em vez de falhar.
        """
        response = requests.get(
            "https://api.twitch.tv/helix/eventsub/subscriptions",
            headers=headers,
            timeout=10
        )
        response.raise_for_status()

        for sub in response.json().get("data", []):
            condition = sub.get("condition", {})
            if (sub.get("type") == "channel.chat.message"
                    and str(condition.get("broadcaster_user_id")) == str(broadcaster_id)
                    and str(condition.get("user_id")) == str(user_id_bot)):
                return sub

        return None

    @staticmethod
    def delete_eventsub_subscription(headers: dict, subscription_id: str):
        """Apaga uma inscrição na Twitch. Se ela já não existir (404), não há o que fazer."""
        response = requests.delete(
            "https://api.twitch.tv/helix/eventsub/subscriptions",
            headers=headers,
            params={"id": subscription_id},
            timeout=10
        )
        if response.status_code not in (204, 404):
            raise RuntimeError(
                f"Erro ao apagar a inscrição {subscription_id} na Twitch: {response.status_code} - {response.text}"
            )

    @staticmethod
    def event_sub_signature(platform_id : str):
        conn = PostgresPool.get_conn()
        try:
            repo_auth = PostgresRepositoryAuth(conn)
            url_base = api_config["URL_BASE"]

            # Pega um App Access Token válido. Se estiver faltando ou vencido,
            # o próprio serviço gera outro e grava no banco.
            app_access_token = AuthService(conn).get_app_access_token()

            # IDs do broadcaster e do bot
            #platform_id = "102089057"

            user_id_bot = twitch["BOT_PLATFORM_ID"]

            # O segredo vem do .env. No banco só fica a impressão digital dele,
            # que diz com qual segredo cada inscrição foi criada.
            webhook_secret = get_webhook_secret()
            fingerprint = impressao_digital_segredo(webhook_secret)

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
                    "secret": webhook_secret
                }
            }

            def criar_inscricao():
                return requests.post(
                    "https://api.twitch.tv/helix/eventsub/subscriptions",
                    headers=headers,
                    json=body
                )

            response = criar_inscricao()

            if response.status_code == 202:
                sub = response.json()["data"][0]

            elif response.status_code == 409:
                # Já existe na Twitch: quem estava desatualizado era o banco.
                sub = TwitchAuthController.find_eventsub_subscription(headers, platform_id, user_id_bot)
                if sub is None:
                    raise RuntimeError(
                        f"A Twitch diz que a inscrição já existe, mas ela não apareceu na listagem: {response.text}"
                    )

                # Se o callback dela for outro (uma URL antiga de ngrok, por
                # exemplo), reaproveitar deixaria o banco dizendo 'enabled'
                # enquanto os eventos vão para outro lugar.
                callback_atual = sub.get("transport", {}).get("callback")
                if callback_atual != f"{url_base}/twitch/eventsub":
                    raise RuntimeError(
                        f"A inscrição {sub['id']} já existe mas aponta para {callback_atual}, "
                        f"e não para {url_base}/twitch/eventsub. Apague ela na Twitch e rode de novo."
                    )

                # A Twitch assina cada evento com o segredo dado na criação da
                # inscrição, e não deixa trocá-lo depois. Só dá para reaproveitar
                # se o banco confirmar que ela foi criada com o segredo atual;
                # senão (segredo trocado, ou banco apagado) é apagar e criar de novo.
                if repo_auth.select_webhook_fingerprint(sub["id"]) == fingerprint:
                    print(f"[INFO] Inscrição já existia na Twitch, reaproveitando: {sub['id']}")
                else:
                    print(f"[INFO] Inscrição {sub['id']} foi criada com outro segredo (ou o banco não a conhece). Recriando...")
                    TwitchAuthController.delete_eventsub_subscription(headers, sub["id"])
                    repo_auth.delete_eventsub_subscription(sub["id"])

                    response = criar_inscricao()
                    if response.status_code != 202:
                        raise RuntimeError(
                            f"Erro ao recriar a EventSub subscription: {response.status_code} - {response.text}"
                        )
                    sub = response.json()["data"][0]

            else:
                raise RuntimeError(f"Erro ao criar EventSub subscription: {response.status_code} - {response.text}")

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
                webhook_secret=fingerprint,
                expires_at=str(datetime.fromisoformat(expires_at.replace("Z", "+00:00")))
            )

            print(f"[INFO] EventSub subscription criada com sucesso: {sub['id']}")

        finally:
            PostgresPool.release_conn(conn)


def setup_auth_routes():
    controller = TwitchAuthController()
    return controller.router
