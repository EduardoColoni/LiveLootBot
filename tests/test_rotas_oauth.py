"""
Callbacks de OAuth do streamer e da conta do bot (/twitch_callback/streamer e /bot).
"""
import base64
import json
import urllib.parse

import requests

from conftest import BOT_ID


def _state(**campos):
    return urllib.parse.quote_plus(base64.b64encode(json.dumps(dict(campos, csrf="x")).encode()).decode())


def _callback(api, rota, code, state):
    return requests.get(f"{api}/twitch_callback/{rota}", params={"code": code, "state": urllib.parse.unquote(state)}, timeout=10)


def test_streamer_autenticado_tem_o_token_gravado_cifrado(api, twitch, repo, sql):
    twitch.contas["code-streamer"] = {"id": "111", "login": "canal_teste"}

    r = _callback(api, "streamer", "code-streamer", _state(guild_id="guild1"))

    assert r.status_code == 200 and "sucesso" in r.text
    token = repo.select_token_by_platform("111")
    assert token["access_token"].startswith("tk-")
    assert token["access_token"] not in sql("SELECT token::text FROM streamer_platform")[0][0]


def test_bot_com_a_conta_certa_e_gravado(api, twitch, repo, streamer):
    twitch.contas["code-bot"] = {"id": BOT_ID, "login": "conta_do_bot"}

    r = _callback(api, "bot", "code-bot", _state(guild_id=streamer["guild_id"]))

    assert r.status_code == 200
    assert repo.select_token_by_platform(BOT_ID)["access_token"].startswith("tk-")


def test_bot_com_a_conta_errada_e_recusado(api, twitch, repo, streamer):
    twitch.contas["code-errado"] = {"id": "111", "login": "canal_teste"}  # autorizou logado como o streamer

    r = _callback(api, "bot", "code-errado", _state(guild_id=streamer["guild_id"]))

    assert r.status_code == 400 and "Conta errada" in r.text
    assert repo.select_token_by_platform(BOT_ID) is None


def test_bot_sem_streamer_no_servidor_e_recusado(api, twitch, repo):
    twitch.contas["code-bot"] = {"id": BOT_ID, "login": "conta_do_bot"}

    r = _callback(api, "bot", "code-bot", _state(guild_id="servidor-sem-streamer"))

    assert r.status_code == 400
    assert repo.select_token_by_platform(BOT_ID) is None


def test_bot_com_state_malformado(api, twitch):
    r = requests.get(f"{api}/twitch_callback/bot", params={"code": "c", "state": "nao-e-base64-json"}, timeout=10)

    assert r.status_code == 400


def test_streamer_com_canal_ja_usado_em_outro_servidor_recebe_mensagem_clara(api, twitch, streamer, sql):
    """O banco recusa o mesmo canal em dois servidores; a pessoa precisa saber por quê."""
    twitch.contas["code-streamer"] = {"id": streamer["platform_id"], "login": "canal_teste"}

    r = _callback(api, "streamer", "code-streamer", _state(guild_id="outro-servidor"))

    assert r.status_code == 409
    assert "outro servidor" in r.text
    assert sql("SELECT guild_id FROM streamer") == [(streamer["guild_id"],)]
