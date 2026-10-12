"""
Envio de mensagem no chat (/twitch_chatters/send_message): concorrência e
renovação do token do bot.
"""
import threading
import time

import requests

from conftest import BOT_ID


def _enviar(api, controle="claim"):
    return requests.post(f"{api}/twitch_chatters/send_message", timeout=30, params={
        "platform_id": "111", "user_name": "fulano", "item_name": "Teclado", "message_control": controle,
    })


def _gravar_token_do_bot(repo, streamer, twitch):
    token = twitch._novo_token({"id": BOT_ID, "login": "bot"})
    repo.insert_bot_token(token, streamer["streamer_id"], BOT_ID)
    return token


def test_mensagem_chega_na_twitch_com_o_texto_do_claim(api, repo, streamer, twitch):
    _gravar_token_do_bot(repo, streamer, twitch)

    r = _enviar(api)

    assert r.status_code == 200
    assert twitch.mensagens[0]["broadcaster_id"] == "111"
    assert twitch.mensagens[0]["sender_id"] == BOT_ID
    assert "@fulano" in twitch.mensagens[0]["message"] and "!claim" in twitch.mensagens[0]["message"]


def test_sem_token_do_bot_devolve_503(api, streamer, twitch):
    r = _enviar(api)

    assert r.status_code == 503
    assert "Autenticação do Bot" in r.json()["detail"]


def test_token_vencido_e_renovado_e_regravado_cifrado(api, repo, sql, streamer, twitch):
    antigo = _gravar_token_do_bot(repo, streamer, twitch)
    twitch.tokens_revogados.add(antigo["access_token"])

    r = _enviar(api)

    assert r.status_code == 200
    novo = repo.select_token_by_platform(BOT_ID)
    assert novo["access_token"] != antigo["access_token"]
    assert novo["access_token"] not in sql("SELECT token::text FROM streamer_platform WHERE platform_id = %s", BOT_ID)[0][0]
    assert len(twitch.mensagens) == 1


def test_requisicoes_simultaneas_nao_esperam_umas_pelas_outras(api, repo, streamer, twitch):
    """
    A rota é síncrona de propósito: o FastAPI a roda num pool de threads. Se
    fosse async com requests bloqueante dentro, três envios de 1s levariam 3s.
    """
    _gravar_token_do_bot(repo, streamer, twitch)
    twitch.atraso_mensagem = 1.0
    respostas = []

    threads = [threading.Thread(target=lambda: respostas.append(_enviar(api))) for _ in range(3)]
    inicio = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    duracao = time.perf_counter() - inicio

    print(f"\n3 envios simultâneos de 1s cada: {duracao:.2f}s")
    assert [r.status_code for r in respostas] == [200, 200, 200]
    assert duracao < 2.0, f"as requisições ficaram em fila ({duracao:.2f}s)"
