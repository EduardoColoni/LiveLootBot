"""
Infraestrutura comum dos testes.

Os testes rodam contra PostgreSQL e Redis DE VERDADE, os mesmos que o
docker compose sobe. Para não encostar nos dados reais:

- o PostgreSQL usa um banco próprio, recriado do zero a cada execução a partir
  do migrations/000_schema_inicial.sql (padrão: live_loot_bot_pytest)
- o Redis usa outro número de banco (padrão: 15), esvaziado a cada teste
- a chave de criptografia e o segredo do webhook são gerados só para os testes

A Twitch é a única coisa simulada (classe TwitchFalsa): nenhum teste sai para
a internet. A API sobe de verdade com uvicorn, numa thread, e as requisições
são HTTP de verdade, inclusive as assinaturas HMAC do webhook.
"""
import hashlib
import hmac
import json
import os
import pathlib
import socket
import threading
import time
import uuid

import psycopg2
import psycopg2.pool
import pytest
import requests
from cryptography.fernet import Fernet
from dotenv import load_dotenv

RAIZ = pathlib.Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Ambiente: precisa ficar pronto ANTES de qualquer import de src, porque o
# config.py lê as variáveis no momento do import.
# ---------------------------------------------------------------------------

# Credenciais do banco e do Redis vêm do src/.env (ou do ambiente, se definidas)
load_dotenv(RAIZ / "src" / ".env")

BANCO_REAL = os.getenv("DB_NAME")
REDIS_DB_REAL = os.getenv("REDIS_DB", "0")

BANCO_TESTE = os.getenv("TEST_DB_NAME", "live_loot_bot_pytest")
REDIS_DB_TESTE = os.getenv("TEST_REDIS_DB", "15")

if BANCO_TESTE == BANCO_REAL:
    raise RuntimeError(f"TEST_DB_NAME não pode ser o banco da aplicação ({BANCO_REAL}): ele é apagado a cada execução.")
if REDIS_DB_TESTE == REDIS_DB_REAL:
    raise RuntimeError(f"TEST_REDIS_DB não pode ser o banco do Redis da aplicação ({REDIS_DB_REAL}): ele é esvaziado a cada teste.")

SEGREDO_WEBHOOK = "segredo-so-dos-testes-0123456789abcdef"
SEGREDO_ANTIGO = "umSegredoForteAqui123"  # o que ficou exposto no repositório
BOT_ID = "999"
URL_BASE = "https://teste.ngrok-free.app"

os.environ.update({
    "DB_NAME": BANCO_TESTE,
    "REDIS_DB": REDIS_DB_TESTE,
    "REDIS_HOST": os.getenv("REDIS_HOST", "localhost"),
    "REDIS_PORT": os.getenv("REDIS_PORT", "6379"),
    "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    "TWITCH_WEBHOOK_SECRET": SEGREDO_WEBHOOK,
    "BOT_PLATFORM_ID": BOT_ID,
    "CLIENT_ID": "client-id-dos-testes",
    "CLIENT_SECRET": "client-secret-dos-testes",
    "TWITCH_URL": "https://id.twitch.tv/oauth2",
    "URL_BASE": URL_BASE,
    "REDIRECT_URI_STREAMER": f"{URL_BASE}/twitch_callback/streamer",
    "REDIRECT_URI_VIEWER": f"{URL_BASE}/twitch_callback/viewer",
    "REDIRECT_URI_BOT": f"{URL_BASE}/twitch_callback/bot",
})

from src.database.postgres.connection.postgres_connection import PostgresPool  # noqa: E402


def _conectar(dbname):
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
        dbname=dbname,
        connect_timeout=5,
    )
    conn.autocommit = True
    return conn


# ---------------------------------------------------------------------------
# Banco e Redis
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def banco_de_teste():
    """Recria o banco de teste com o schema versionado e inicia o pool."""
    try:
        admin = _conectar("postgres")
    except psycopg2.OperationalError as e:
        pytest.exit(
            f"PostgreSQL inacessível em {os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', 5432)}. "
            f"Suba a infraestrutura (cd PostDocker && docker compose up -d).\n{e}",
            returncode=1,
        )

    with admin.cursor() as cur:
        cur.execute(f'DROP DATABASE IF EXISTS "{BANCO_TESTE}" WITH (FORCE)')
        cur.execute(f'CREATE DATABASE "{BANCO_TESTE}"')
    admin.close()

    schema = (RAIZ / "migrations" / "000_schema_inicial.sql").read_text(encoding="utf-8")
    conn = _conectar(BANCO_TESTE)
    with conn.cursor() as cur:
        cur.execute(schema)
    conn.close()

    PostgresPool.init_pool(minconn=1, maxconn=5)
    yield
    try:
        PostgresPool.close_all()
    except psycopg2.pool.PoolError:
        pass  # a API, se subiu, já fechou o pool ao encerrar


@pytest.fixture
def sql():
    """Executa SQL direto no banco de teste, por fora da aplicação (o que o DBeaver veria)."""
    conn = _conectar(BANCO_TESTE)

    def executar(query, *params):
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall() if cur.description else None

    yield executar
    conn.close()


@pytest.fixture
def redis_teste():
    import redis
    return redis.Redis(host=os.environ["REDIS_HOST"], port=int(os.environ["REDIS_PORT"]), db=int(REDIS_DB_TESTE))


@pytest.fixture(autouse=True)
def estado_limpo(sql, redis_teste):
    """Cada teste começa com o banco e o Redis vazios."""
    sql("TRUNCATE streamer, app_access_token RESTART IDENTITY CASCADE")
    try:
        redis_teste.flushdb()
    except Exception as e:
        pytest.exit(f"Redis inacessível em {os.environ['REDIS_HOST']}:{os.environ['REDIS_PORT']}: {e}", returncode=1)
    yield


@pytest.fixture
def conn():
    c = PostgresPool.get_conn()
    yield c
    PostgresPool.release_conn(c)


@pytest.fixture
def repo(conn):
    from src.database.postgres.postgres_repository_auth import PostgresRepositoryAuth
    return PostgresRepositoryAuth(conn)


@pytest.fixture
def streamer(repo):
    """Um streamer autenticado (canal 111, servidor do Discord 'guild1'), com o token já cifrado."""
    repo.new_insert_token(
        {"access_token": "STREAMER_ACCESS", "refresh_token": "STREAMER_REFRESH", "expires_in": 14000},
        "guild1", "canal_teste", "111", "twitch",
    )
    return {"guild_id": "guild1", "platform_id": "111", "streamer_id": repo.select_streamer_id("guild1")}


# ---------------------------------------------------------------------------
# API real
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def api():
    """Sobe a API de verdade (uvicorn) numa thread e devolve a URL base."""
    import uvicorn
    from src.api.main_api import app

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]

    servidor = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=porta, log_level="warning"))
    thread = threading.Thread(target=servidor.run, daemon=True)
    thread.start()
    while not servidor.started:
        time.sleep(0.05)

    yield f"http://127.0.0.1:{porta}"

    servidor.should_exit = True
    thread.join(timeout=5)


def enviar_evento(api_url, segredo, tipo, corpo):
    """Envia ao webhook uma mensagem assinada como a Twitch assina (HMAC-SHA256)."""
    message_id = str(uuid.uuid4())
    timestamp = "2026-10-12T12:00:00Z"
    body = json.dumps(corpo)
    assinatura = "sha256=" + hmac.new(
        segredo.encode(), (message_id + timestamp + body).encode(), hashlib.sha256
    ).hexdigest()
    return requests.post(
        f"{api_url}/twitch/eventsub",
        data=body,
        headers={
            "Twitch-Eventsub-Message-Id": message_id,
            "Twitch-Eventsub-Message-Timestamp": timestamp,
            "Twitch-Eventsub-Message-Signature": assinatura,
            "Twitch-Eventsub-Message-Type": tipo,
            "Content-Type": "application/json",
        },
        timeout=10,
    )


def mensagem_de_chat(broadcaster_id, chatter_id, texto, chatter_name="viewer"):
    return {"event": {
        "broadcaster_user_id": broadcaster_id,
        "chatter_user_id": chatter_id,
        "chatter_user_name": chatter_name,
        "message": {"text": texto},
    }}


# ---------------------------------------------------------------------------
# Twitch simulada
# ---------------------------------------------------------------------------

class RespostaFalsa:
    def __init__(self, status_code, dados=None):
        self.status_code = status_code
        self._dados = dados
        self.text = json.dumps(dados) if dados is not None else ""

    def json(self):
        return self._dados

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code}: {self.text}", response=self)


class TwitchFalsa:
    """
    Faz o papel da Twitch: OAuth, /helix/users, EventSub e envio de mensagem.

    Entra no lugar do módulo `requests` dentro dos módulos da aplicação, então
    o resto do código roda sem saber que não está falando com a Twitch.
    """
    exceptions = requests.exceptions

    def __init__(self, api_url=None):
        self.api_url = api_url
        self.contas = {}           # code do OAuth -> {"id", "login"}
        self.tokens = {}           # access_token -> conta
        self.tokens_revogados = set()
        self.inscricoes = {}       # id -> {"secret", "callback", "condition", "verificada"}
        self.chamadas = []         # (método, url resumida, status)
        self.mensagens = []        # corpos enviados para /helix/chat/messages
        self.trocas_de_code = []   # dados enviados ao /oauth2/token com grant_type=authorization_code
        self.atraso_mensagem = 0.0

    # -- requests.* -------------------------------------------------------
    def post(self, url, *args, **kwargs):
        if url.endswith("/oauth2/token"):
            return self._registrar("POST", "token", self._token(kwargs.get("data", {})))
        if url.endswith("/helix/eventsub/subscriptions"):
            return self._registrar("POST", "eventsub", self._criar_inscricao(kwargs["json"]))
        if url.endswith("/helix/chat/messages"):
            return self._registrar("POST", "chat", self._enviar_mensagem(kwargs))
        raise AssertionError(f"POST inesperado na Twitch falsa: {url}")

    def get(self, url, *args, **kwargs):
        if url.endswith("/helix/users"):
            token = kwargs["headers"]["Authorization"].removeprefix("Bearer ")
            conta = self.tokens[token]
            return RespostaFalsa(200, {"data": [{"id": conta["id"], "login": conta["login"], "display_name": conta["login"]}]})
        if url.endswith("/helix/eventsub/subscriptions"):
            return RespostaFalsa(200, {"data": [self._json_inscricao(i) for i in self.inscricoes]})
        raise AssertionError(f"GET inesperado na Twitch falsa: {url}")

    def delete(self, url, *args, **kwargs):
        sub_id = kwargs["params"]["id"]
        status = 204 if self.inscricoes.pop(sub_id, None) else 404
        return self._registrar("DELETE", sub_id, RespostaFalsa(status))

    # -- comportamento ----------------------------------------------------
    def _registrar(self, metodo, alvo, resposta):
        self.chamadas.append((metodo, alvo, resposta.status_code))
        return resposta

    def _novo_token(self, conta=None):
        token = {"access_token": f"tk-{uuid.uuid4().hex[:12]}", "refresh_token": f"rf-{uuid.uuid4().hex[:12]}",
                 "expires_in": 14000, "token_type": "bearer"}
        if conta:
            self.tokens[token["access_token"]] = conta
        return token

    def _token(self, dados):
        tipo = dados.get("grant_type")
        if tipo == "client_credentials":
            return RespostaFalsa(200, {"access_token": f"app-{uuid.uuid4().hex[:12]}", "expires_in": 5000000, "token_type": "bearer"})
        if tipo == "authorization_code":
            self.trocas_de_code.append(dados)
            conta = self.contas.get(dados["code"])
            if not conta:
                return RespostaFalsa(400, {"message": "Invalid authorization code"})
            return RespostaFalsa(200, self._novo_token(conta))
        if tipo == "refresh_token":
            return RespostaFalsa(200, self._novo_token({"id": BOT_ID, "login": "bot"}))
        raise AssertionError(f"grant_type inesperado: {tipo}")

    def _criar_inscricao(self, corpo):
        for inscricao in self.inscricoes.values():
            if inscricao["condition"] == corpo["condition"]:
                return RespostaFalsa(409, {"error": "Conflict", "message": "subscription already exists"})

        sub_id = str(uuid.uuid4())
        self.inscricoes[sub_id] = {
            "secret": corpo["transport"]["secret"],
            "callback": corpo["transport"]["callback"],
            "condition": corpo["condition"],
            "verificada": False,
        }
        # Como a Twitch real: manda o desafio assinado com o segredo da inscrição
        if self.api_url:
            r = enviar_evento(self.api_url, corpo["transport"]["secret"], "webhook_callback_verification",
                              {"challenge": "desafio-123", "subscription": {"id": sub_id}})
            self.inscricoes[sub_id]["verificada"] = r.status_code == 200 and r.text == "desafio-123"
        return RespostaFalsa(202, {"data": [self._json_inscricao(sub_id)]})

    def _json_inscricao(self, sub_id):
        i = self.inscricoes[sub_id]
        return {
            "id": sub_id,
            "type": "channel.chat.message",
            "condition": i["condition"],
            "status": "enabled" if i["verificada"] else "webhook_callback_verification_pending",
            "transport": {"method": "webhook", "callback": i["callback"]},
            "created_at": "2026-10-12T12:00:00Z",
        }

    def _enviar_mensagem(self, kwargs):
        token = kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        if token in self.tokens_revogados:
            return RespostaFalsa(401, {"message": "Invalid OAuth token"})
        time.sleep(self.atraso_mensagem)
        self.mensagens.append(kwargs["json"])
        return RespostaFalsa(200, {"data": [{"message_id": str(uuid.uuid4()), "is_sent": True}]})

    def criar_inscricao_existente(self, secret, callback=f"{URL_BASE}/twitch/eventsub", sub_id=None):
        """Simula uma inscrição que já estava na Twitch antes do teste."""
        sub_id = sub_id or str(uuid.uuid4())
        self.inscricoes[sub_id] = {
            "secret": secret,
            "callback": callback,
            "condition": {"broadcaster_user_id": "111", "user_id": BOT_ID},
            "verificada": True,
        }
        return sub_id


@pytest.fixture
def twitch(monkeypatch, request):
    """Troca o `requests` dos módulos da aplicação pela Twitch simulada."""
    from src.api.routes import twitch_auth_route, twitch_chatters_routes
    from src.api.services import auth_service

    api_url = request.getfixturevalue("api") if "api" in request.fixturenames else None
    falsa = TwitchFalsa(api_url)
    for modulo in (twitch_auth_route, twitch_chatters_routes, auth_service):
        monkeypatch.setattr(modulo, "requests", falsa)
    return falsa
