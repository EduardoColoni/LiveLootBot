"""
Criação da inscrição de chat no EventSub: automática, ao autenticar a conta do bot
(/twitch_callback/bot), ou à mão (/twitch_callback/event_sub_signature).

A Twitch assina cada evento com o segredo dado na criação da inscrição e não
deixa trocá-lo. Por isso, quando ela responde 409 (já existe), a inscrição só
pode ser reaproveitada se foi criada com o segredo atual.
"""
import base64
import json

import requests

from conftest import BOT_ID, SEGREDO_ANTIGO, SEGREDO_WEBHOOK, URL_BASE, RespostaFalsa, enviar_evento, mensagem_de_chat
from src.core.criptografia import impressao_digital_segredo


def _criar(api):
    return requests.get(f"{api}/twitch_callback/event_sub_signature", params={"platform_id": "111"}, timeout=30)


def _unica_inscricao(twitch):
    assert len(twitch.inscricoes) == 1, twitch.inscricoes
    return next(iter(twitch.inscricoes.items()))


def _deletes(twitch):
    return [c for c in twitch.chamadas if c[0] == "DELETE"]


def test_primeira_criacao(api, streamer, twitch, sql):
    assert _criar(api).status_code == 200

    sub_id, inscricao = _unica_inscricao(twitch)
    assert inscricao["secret"] == SEGREDO_WEBHOOK
    assert inscricao["verificada"], "o desafio da Twitch deveria ter sido respondido"
    assert sql("SELECT subscription_id, webhook_secret FROM twitch_eventsub_subscription") == \
        [(sub_id, impressao_digital_segredo(SEGREDO_WEBHOOK))]


def test_segredo_real_nunca_vai_para_o_banco(api, streamer, twitch, sql):
    _criar(api)

    assert SEGREDO_WEBHOOK not in str(sql("SELECT * FROM twitch_eventsub_subscription"))


def test_409_com_o_segredo_atual_reaproveita(api, streamer, twitch):
    _criar(api)
    sub_id, _ = _unica_inscricao(twitch)
    twitch.chamadas.clear()

    assert _criar(api).status_code == 200

    assert _unica_inscricao(twitch)[0] == sub_id
    assert _deletes(twitch) == []


def test_409_de_inscricao_antiga_com_banco_apagado_recria(api, streamer, twitch, redis_teste):
    """O cenário de quem troca o segredo e apaga o banco (docker compose down -v)."""
    antiga = twitch.criar_inscricao_existente(SEGREDO_ANTIGO)

    assert _criar(api).status_code == 200

    sub_id, inscricao = _unica_inscricao(twitch)
    assert sub_id != antiga
    assert inscricao["secret"] == SEGREDO_WEBHOOK and inscricao["verificada"]
    assert _deletes(twitch) == [("DELETE", antiga, 204)]

    # E o !claim, agora assinado com o segredo novo, chega
    enviar_evento(api, inscricao["secret"], "notification", mensagem_de_chat("111", "555", "!claim"))
    assert redis_teste.get("claim:twitch:111:555") is not None


def test_409_com_impressao_digital_antiga_no_banco_recria(api, streamer, twitch, sql):
    antiga = twitch.criar_inscricao_existente(SEGREDO_ANTIGO)
    sql("""INSERT INTO twitch_eventsub_subscription
           (streamer_id, platform_id, subscription_id, status, type, transport_callback, webhook_secret, expires_at)
           VALUES (%s, '111', %s, 'enabled', 'channel.chat.message', 'x', %s, NOW())""",
        streamer["streamer_id"], antiga, impressao_digital_segredo(SEGREDO_ANTIGO))

    _criar(api)

    sub_id, inscricao = _unica_inscricao(twitch)
    assert inscricao["secret"] == SEGREDO_WEBHOOK
    assert sql("SELECT subscription_id FROM twitch_eventsub_subscription") == [(sub_id,)]


def test_409_com_callback_de_outra_url_recria_no_endereco_atual(api, streamer, twitch, redis_teste):
    """
    Domínio do ngrok trocado (URL_BASE novo): a inscrição antiga manda os eventos para um
    endereço que não é mais o desta API. Ela é apagada e criada de novo no endereço atual.
    O segredo da antiga é o atual de propósito: só o endereço está errado.
    """
    outra = twitch.criar_inscricao_existente(SEGREDO_WEBHOOK, callback="https://antigo.ngrok-free.app/twitch/eventsub")

    assert _criar(api).status_code == 200

    sub_id, inscricao = _unica_inscricao(twitch)
    assert sub_id != outra
    assert inscricao["callback"] == f"{URL_BASE}/twitch/eventsub" and inscricao["verificada"]
    assert _deletes(twitch) == [("DELETE", outra, 204)]

    enviar_evento(api, inscricao["secret"], "notification", mensagem_de_chat("111", "555", "!claim"))
    assert redis_teste.get("claim:twitch:111:555") is not None


# ---------------------------------------------------------------------------
# Inscrição automática ao autenticar a conta do bot
# ---------------------------------------------------------------------------

def _autenticar_bot(api, twitch, guild_id, conta_id=BOT_ID):
    twitch.contas["code-bot"] = {"id": conta_id, "login": "conta_do_bot"}
    state = base64.b64encode(json.dumps({"guild_id": guild_id, "csrf": "x"}).encode()).decode()
    return requests.get(f"{api}/twitch_callback/bot", params={"code": "code-bot", "state": state}, timeout=30)


def test_autenticar_o_bot_cria_a_inscricao_do_canal(api, streamer, twitch, repo, sql):
    r = _autenticar_bot(api, twitch, streamer["guild_id"])

    assert r.status_code == 200 and "chat conectado" in r.text
    assert repo.select_token_by_platform(BOT_ID) is not None
    sub_id, inscricao = _unica_inscricao(twitch)
    assert inscricao["condition"] == {"broadcaster_user_id": streamer["platform_id"], "user_id": BOT_ID}
    assert inscricao["secret"] == SEGREDO_WEBHOOK and inscricao["verificada"]
    assert inscricao["callback"] == f"{URL_BASE}/twitch/eventsub"
    assert sql("SELECT subscription_id, platform_id FROM twitch_eventsub_subscription") == \
        [(sub_id, streamer["platform_id"])]


def test_claim_chega_depois_de_so_autenticar_o_bot(api, streamer, twitch, redis_teste):
    """O fluxo inteiro sem o curl: autentica o bot e o !claim do chat já é gravado."""
    _autenticar_bot(api, twitch, streamer["guild_id"])
    _, inscricao = _unica_inscricao(twitch)

    r = enviar_evento(api, inscricao["secret"], "notification", mensagem_de_chat("111", "555", "!claim"))

    assert r.status_code == 200
    assert redis_teste.get("claim:twitch:111:555") is not None


def test_autenticar_o_bot_de_novo_reaproveita_a_inscricao(api, streamer, twitch):
    _autenticar_bot(api, twitch, streamer["guild_id"])
    sub_id, _ = _unica_inscricao(twitch)
    twitch.chamadas.clear()

    r = _autenticar_bot(api, twitch, streamer["guild_id"])

    assert r.status_code == 200 and "chat conectado" in r.text
    assert _unica_inscricao(twitch)[0] == sub_id
    assert _deletes(twitch) == []


def test_falha_ao_criar_a_inscricao_nao_perde_o_token_do_bot(api, streamer, twitch, repo, sql, monkeypatch):
    monkeypatch.setattr(twitch, "_criar_inscricao",
                        lambda corpo: RespostaFalsa(503, {"error": "Service Unavailable", "status": 503}))

    r = _autenticar_bot(api, twitch, streamer["guild_id"])

    assert r.status_code != 200
    assert "Bot autenticado" in r.text and "chat" in r.text and "503" in r.text
    assert repo.select_token_by_platform(BOT_ID) is not None
    assert sql("SELECT * FROM twitch_eventsub_subscription") == []


def test_bot_com_a_conta_errada_nao_cria_inscricao(api, streamer, twitch, sql):
    r = _autenticar_bot(api, twitch, streamer["guild_id"], conta_id=streamer["platform_id"])

    assert r.status_code == 400
    assert twitch.inscricoes == {}
    assert sql("SELECT * FROM twitch_eventsub_subscription") == []
