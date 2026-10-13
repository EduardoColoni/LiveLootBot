"""
Webhook do EventSub (/twitch/eventsub): validação HMAC-SHA256 e gravação do claim.
As assinaturas são montadas de verdade, sem contornar a validação.
"""
import hashlib
import hmac

import requests

from conftest import SEGREDO_ANTIGO, SEGREDO_WEBHOOK, BOT_ID, enviar_evento, mensagem_de_chat


def test_desafio_de_verificacao_e_respondido(api):
    r = enviar_evento(api, SEGREDO_WEBHOOK, "webhook_callback_verification", {"challenge": "abc-123"})

    assert r.status_code == 200
    assert r.text == "abc-123"


def test_assinatura_com_segredo_antigo_devolve_403(api, redis_teste):
    r = enviar_evento(api, SEGREDO_ANTIGO, "notification", mensagem_de_chat("111", "555", "!claim"))

    assert r.status_code == 403
    assert redis_teste.keys("claim:*") == []


def test_corpo_adulterado_devolve_403(api):
    # Assinatura válida para um corpo, enviada com outro: o HMAC não bate
    message_id, timestamp = "id-1", "2026-10-12T12:00:00Z"
    original = '{"challenge": "abc"}'
    assinatura = "sha256=" + hmac.new(SEGREDO_WEBHOOK.encode(), (message_id + timestamp + original).encode(),
                                      hashlib.sha256).hexdigest()

    r = requests.post(f"{api}/twitch/eventsub", data='{"challenge": "outro"}', timeout=10, headers={
        "Twitch-Eventsub-Message-Id": message_id,
        "Twitch-Eventsub-Message-Timestamp": timestamp,
        "Twitch-Eventsub-Message-Signature": assinatura,
        "Twitch-Eventsub-Message-Type": "webhook_callback_verification",
    })
    assert r.status_code == 403


def test_claim_grava_a_chave_com_canal_e_viewer(api, redis_teste):
    r = enviar_evento(api, SEGREDO_WEBHOOK, "notification",
                      mensagem_de_chat("111", "555", "!claim", chatter_name="fulano"))

    assert r.status_code == 200
    assert redis_teste.get("claim:twitch:111:555") == b"fulano"
    assert 0 < redis_teste.ttl("claim:twitch:111:555") <= 17


def test_mensagem_comum_nao_grava_claim(api, redis_teste):
    enviar_evento(api, SEGREDO_WEBHOOK, "notification", mensagem_de_chat("111", "555", "boa noite"))

    assert redis_teste.keys("claim:*") == []


def test_mensagem_do_proprio_bot_e_descartada(api, redis_teste):
    r = enviar_evento(api, SEGREDO_WEBHOOK, "notification", mensagem_de_chat("111", BOT_ID, "!claim"))

    assert r.status_code == 200
    assert redis_teste.keys("claim:*") == []
