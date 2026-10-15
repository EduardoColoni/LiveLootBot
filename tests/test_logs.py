"""
Log de acesso do uvicorn: a linha de cada requisição não pode levar a query string, que
traz o state do OAuth (id e nome do Discord do viewer em base64) e o nome do ganhador.
"""
import logging


def _linha_de_acesso(caminho):
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d', ("172.18.0.2:41748", "GET", caminho, "1.1", 200), None,
    )


def _filtrar(registro):
    import src.api.main_api  # noqa: F401  (registra o filtro ao importar a aplicação)
    for filtro in logging.getLogger("uvicorn.access").filters:
        filtro.filter(registro)
    return registro.getMessage()


def test_log_de_acesso_nao_mostra_a_query_string():
    linha = _filtrar(_linha_de_acesso("/twitch_callback/viewer?code=abc123&state=eyJndWlsZF9pZCI6IDF9"))

    assert linha == '172.18.0.2:41748 - "GET /twitch_callback/viewer HTTP/1.1" 200'


def test_log_de_acesso_sem_query_fica_igual():
    linha = _filtrar(_linha_de_acesso("/twitch/eventsub"))

    assert linha == '172.18.0.2:41748 - "GET /twitch/eventsub HTTP/1.1" 200'
