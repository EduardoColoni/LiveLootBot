"""
Links de autorização que o bot manda no Discord (/autenticar_plataformas e !autenticar).

O redirect_uri do link precisa estar cadastrado no app da Twitch e, pelo
OAuth (RFC 6749, 4.1.3), ser o mesmo enviado depois na troca do code pelo
token. Os links já tiveram o endereço do ngrok do autor fixo no código, e o
callback do viewer trocava o code com o endereço do streamer.
"""
import os
import urllib.parse

import pytest
import requests

from conftest import URL_BASE


def _parametros(link):
    return {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(link).query).items()}


@pytest.fixture
def servico(conn):
    from src.bot.services.raffle_service import RaffleService
    return RaffleService(conn, "guild1")


@pytest.mark.parametrize("plataforma, variavel", [("twitch", "REDIRECT_URI_STREAMER"), ("twitch_bot", "REDIRECT_URI_BOT")])
def test_links_do_streamer_usam_o_endereco_do_env(servico, plataforma, variavel):
    link = servico.streamer_auth_method("guild1")[plataforma]

    assert _parametros(link)["redirect_uri"] == os.environ[variavel]


def test_link_do_viewer_usa_o_endereco_do_env(servico):
    link = servico.viewer_auth_method("guild1", "d1", "fulano")["twitch"]

    assert _parametros(link)["redirect_uri"] == os.environ["REDIRECT_URI_VIEWER"]


def test_nenhum_link_tem_endereco_fixo(servico):
    links = list(servico.streamer_auth_method("guild1").values()) + \
            list(servico.viewer_auth_method("guild1", "d1", "fulano").values())

    for link in links:
        assert urllib.parse.urlparse(_parametros(link)["redirect_uri"]).netloc == urllib.parse.urlparse(URL_BASE).netloc


@pytest.mark.parametrize("rota, gerar_link", [
    ("streamer", lambda s: s.streamer_auth_method("guild1")["twitch"]),
    ("viewer", lambda s: s.viewer_auth_method("guild1", "d1", "fulano")["twitch"]),
])
def test_redirect_uri_do_link_e_o_mesmo_da_troca_do_code(api, twitch, servico, streamer, rota, gerar_link):
    """O fluxo inteiro: link gerado pelo bot -> callback na API -> troca do code na Twitch."""
    link = _parametros(gerar_link(servico))
    twitch.contas["code-x"] = {"id": "555", "login": "fulano"}

    requests.get(f"{api}/twitch_callback/{rota}", params={"code": "code-x", "state": link["state"]}, timeout=10)

    assert len(twitch.trocas_de_code) == 1
    assert twitch.trocas_de_code[0]["redirect_uri"] == link["redirect_uri"]
