"""
Rotas de manutenção (/twitch_callback/twitch_app_access_token e /event_sub_signature):
só atendem quem está na máquina da API (curl em localhost). A API fica aberta na
internet pelo ngrok, e por lá elas deixariam qualquer um gerar tokens do app,
recriar a inscrição do chat e, antes, até ler o App Access Token.

Pelo ngrok a requisição chega de dois jeitos, e os dois são recusados:
- ngrok em contêiner (o do README): vem do IP do contêiner, na rede do Docker;
- ngrok rodando direto na máquina: vem de 127.0.0.1, mas com X-Forwarded-For, que
  o uvicorn usa para trocar o endereço do cliente pelo de quem está na internet.
"""
import pytest
import requests
from fastapi import HTTPException
from starlette.requests import Request

from conftest import SEGREDO_WEBHOOK


def _get(api, rota, **kwargs):
    return requests.get(f"{api}/twitch_callback/{rota}", timeout=30, **kwargs)


VINDO_DO_NGROK = {"X-Forwarded-For": "203.0.113.7", "X-Forwarded-Proto": "https"}


# ---------------------------------------------------------------------------
# Pela internet (ngrok)
# ---------------------------------------------------------------------------

def test_app_access_token_pelo_ngrok_e_recusado(api, twitch, sql):
    r = _get(api, "twitch_app_access_token", headers=VINDO_DO_NGROK)

    assert r.status_code == 403
    assert twitch.chamadas == [], "não deveria ter falado com a Twitch"
    assert sql("SELECT * FROM app_access_token") == []


def test_inscricao_manual_pelo_ngrok_e_recusada(api, twitch, streamer, sql):
    r = _get(api, "event_sub_signature", params={"platform_id": streamer["platform_id"]}, headers=VINDO_DO_NGROK)

    assert r.status_code == 403
    assert twitch.chamadas == [] and twitch.inscricoes == {}
    assert sql("SELECT * FROM twitch_eventsub_subscription") == []


@pytest.mark.parametrize("ip", ["172.18.0.4", "192.168.0.10", "203.0.113.7"])
def test_conexao_de_fora_da_maquina_e_recusada(ip):
    """O ngrok do compose chega pela rede do Docker (no log do autor, 172.18.0.4)."""
    from src.api.routes.twitch_auth_route import somente_local
    requisicao = Request({"type": "http", "client": (ip, 50000), "headers": []})

    with pytest.raises(HTTPException) as erro:
        somente_local(requisicao)

    assert erro.value.status_code == 403


# ---------------------------------------------------------------------------
# Na máquina da API (curl em localhost)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ip", ["127.0.0.1", "::1"])
def test_conexao_da_propria_maquina_e_aceita(ip):
    from src.api.routes.twitch_auth_route import somente_local
    somente_local(Request({"type": "http", "client": (ip, 50000), "headers": []}))


def test_app_access_token_local_gera_mas_nao_devolve_o_token(api, twitch, repo):
    r = _get(api, "twitch_app_access_token")

    assert r.status_code == 200
    gravado = repo.select_app_access_token()["access_token"]
    assert gravado.startswith("app-")
    assert gravado not in r.text


def test_inscricao_manual_local_continua_funcionando(api, twitch, streamer):
    r = _get(api, "event_sub_signature", params={"platform_id": streamer["platform_id"]})

    assert r.status_code == 200
    (inscricao,) = twitch.inscricoes.values()
    assert inscricao["secret"] == SEGREDO_WEBHOOK and inscricao["verificada"]


def test_callbacks_de_oauth_continuam_abertos_pelo_ngrok(api, twitch, streamer):
    """A Twitch redireciona o navegador da pessoa para eles: precisam continuar públicos."""
    import base64, json
    from conftest import BOT_ID
    twitch.contas["c"] = {"id": BOT_ID, "login": "bot"}
    state = base64.b64encode(json.dumps({"guild_id": streamer["guild_id"], "csrf": "x"}).encode()).decode()

    r = _get(api, "bot", params={"code": "c", "state": state}, headers=VINDO_DO_NGROK)

    assert r.status_code == 200 and "chat conectado" in r.text
