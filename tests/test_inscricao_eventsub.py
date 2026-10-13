"""
Criação da inscrição de chat no EventSub (/twitch_callback/event_sub_signature).

A Twitch assina cada evento com o segredo dado na criação da inscrição e não
deixa trocá-lo. Por isso, quando ela responde 409 (já existe), a inscrição só
pode ser reaproveitada se foi criada com o segredo atual.
"""
import requests

from conftest import SEGREDO_ANTIGO, SEGREDO_WEBHOOK, enviar_evento, mensagem_de_chat
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


def test_409_com_callback_de_outra_url_continua_dando_erro(api, streamer, twitch):
    outra = twitch.criar_inscricao_existente(SEGREDO_ANTIGO, callback="https://antigo.ngrok-free.app/twitch/eventsub")

    assert _criar(api).status_code == 500
    assert outra in twitch.inscricoes, "não deveria apagar a inscrição de outro endereço"
