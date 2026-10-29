"""
Telas que a API mostra no navegador ao fim de cada autorização (callbacks de OAuth do
streamer, do bot e do viewer).

O visual em si não dá para testar; o que se confere é que toda resposta é a página
estilizada completa (e não um <h1> solto ou um "null"), que o código HTTP de cada caso
continua o mesmo, que o CSS e o logo que ela usa são servidos e que o texto vindo de
fora (nome de conta e resposta da Twitch) aparece escapado, sem virar HTML.
"""
import base64
import json

import pytest
import requests

from conftest import BOT_ID, RespostaFalsa


def _state(**campos):
    return base64.b64encode(json.dumps(dict(campos, csrf="x")).encode()).decode()


def _callback(api, rota, code, state):
    return requests.get(f"{api}/twitch_callback/{rota}", params={"code": code, "state": state}, timeout=30)


def _e_a_pagina_estilizada(r):
    assert r.headers["content-type"].startswith("text/html")
    assert r.text.lstrip().lower().startswith("<!doctype html>")
    assert 'href="/static/css/paginas.css"' in r.text
    assert 'src="/static/img/logo.png"' in r.text


# ---------------------------------------------------------------------------
# Cada desfecho dos callbacks
# ---------------------------------------------------------------------------

def test_streamer_autenticado(api, twitch):
    twitch.contas["c"] = {"id": "111", "login": "canal"}

    r = _callback(api, "streamer", "c", _state(guild_id="g1"))

    assert r.status_code == 200 and "sucesso" in r.text
    _e_a_pagina_estilizada(r)


def test_servidor_que_ja_tem_streamer(api, twitch, streamer):
    twitch.contas["c"] = {"id": "222", "login": "outro_canal"}

    r = _callback(api, "streamer", "c", _state(guild_id=streamer["guild_id"]))

    assert r.status_code == 200 and "Apenas um streamer" in r.text
    _e_a_pagina_estilizada(r)


def test_canal_ja_vinculado_a_outro_servidor(api, twitch, streamer):
    twitch.contas["c"] = {"id": streamer["platform_id"], "login": "canal"}

    r = _callback(api, "streamer", "c", _state(guild_id="outro-servidor"))

    assert r.status_code == 409 and "outro servidor" in r.text
    _e_a_pagina_estilizada(r)


def test_streamer_com_code_recusado_pela_twitch_mostra_a_pagina(api, twitch):
    """Antes, o callback do streamer não respondia nada nesse caso: o navegador mostrava 'null'."""
    r = _callback(api, "streamer", "code-que-a-twitch-nao-conhece", _state(guild_id="g1"))

    assert r.status_code == 400
    assert r.text.strip() != "null"
    _e_a_pagina_estilizada(r)


def test_bot_autenticado(api, twitch, streamer):
    twitch.contas["c"] = {"id": BOT_ID, "login": "bot"}

    r = _callback(api, "bot", "c", _state(guild_id=streamer["guild_id"]))

    assert r.status_code == 200 and "chat conectado" in r.text
    _e_a_pagina_estilizada(r)


def test_bot_com_a_conta_errada(api, twitch, streamer):
    twitch.contas["c"] = {"id": "111", "login": "canal"}

    r = _callback(api, "bot", "c", _state(guild_id=streamer["guild_id"]))

    assert r.status_code == 400 and "Conta errada" in r.text and BOT_ID in r.text
    _e_a_pagina_estilizada(r)


def test_bot_sem_streamer_no_servidor(api, twitch):
    twitch.contas["c"] = {"id": BOT_ID, "login": "bot"}

    r = _callback(api, "bot", "c", _state(guild_id="servidor-vazio"))

    assert r.status_code == 400
    _e_a_pagina_estilizada(r)


def test_bot_com_falha_na_inscricao_do_chat(api, twitch, streamer, monkeypatch):
    monkeypatch.setattr(twitch, "_criar_inscricao", lambda corpo: RespostaFalsa(503, {"status": 503}))
    twitch.contas["c"] = {"id": BOT_ID, "login": "bot"}

    r = _callback(api, "bot", "c", _state(guild_id=streamer["guild_id"]))

    assert r.status_code == 500 and "Bot autenticado" in r.text and "503" in r.text
    _e_a_pagina_estilizada(r)


def test_viewer_autenticado(api, twitch, streamer):
    twitch.contas["c"] = {"id": "555", "login": "fulano"}

    r = _callback(api, "viewer", "c", _state(guild_id=streamer["guild_id"], discord_user_id="d1",
                                             discord_user_name="fulano#1"))

    assert r.status_code == 200 and "sucesso" in r.text
    _e_a_pagina_estilizada(r)


def test_viewer_sem_streamer_no_servidor(api, twitch):
    twitch.contas["c"] = {"id": "555", "login": "fulano"}

    r = _callback(api, "viewer", "c", _state(guild_id="servidor-vazio", discord_user_id="d1",
                                             discord_user_name="fulano#1"))

    assert "Nenhum streamer" in r.text
    _e_a_pagina_estilizada(r)


@pytest.mark.parametrize("rota", ["streamer", "bot", "viewer"])
def test_autorizacao_cancelada_na_twitch(api, rota):
    """Quem clica em 'Cancelar' na Twitch volta sem code."""
    r = requests.get(f"{api}/twitch_callback/{rota}", params={"error": "access_denied", "state": _state(guild_id="g1")},
                     timeout=30)

    assert r.status_code == 400
    _e_a_pagina_estilizada(r)


@pytest.mark.parametrize("rota", ["streamer", "bot", "viewer"])
def test_link_adulterado(api, rota):
    r = requests.get(f"{api}/twitch_callback/{rota}", params={"code": "c", "state": "nao-e-base64-json"}, timeout=30)

    assert r.status_code == 400
    _e_a_pagina_estilizada(r)


# ---------------------------------------------------------------------------
# Arquivos da página e texto vindo de fora
# ---------------------------------------------------------------------------

def test_css_e_logo_sao_servidos(api):
    css = requests.get(f"{api}/static/css/paginas.css", timeout=10)
    logo = requests.get(f"{api}/static/img/logo.png", timeout=10)

    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")
    assert logo.status_code == 200 and logo.headers["content-type"] == "image/png"
    assert logo.content.startswith(b"\x89PNG")


def test_nome_da_conta_aparece_escapado(api, twitch, streamer):
    twitch.contas["c"] = {"id": "111", "login": "<img src=x onerror=alert(1)>"}

    r = _callback(api, "bot", "c", _state(guild_id=streamer["guild_id"]))

    assert "<img src=x" not in r.text
    assert "&lt;img src=x onerror=alert(1)&gt;" in r.text


def test_resposta_da_twitch_aparece_escapada(api, twitch, streamer, monkeypatch):
    monkeypatch.setattr(twitch, "_criar_inscricao",
                        lambda corpo: RespostaFalsa(503, {"message": "<script>alert(1)</script>"}))
    twitch.contas["c"] = {"id": BOT_ID, "login": "bot"}

    r = _callback(api, "bot", "c", _state(guild_id=streamer["guild_id"]))

    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;" in r.text
