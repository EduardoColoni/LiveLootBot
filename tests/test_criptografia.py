"""
Criptografia dos tokens: o que vai para o banco é ilegível, o que volta para o
código é o dicionário original, e nada em texto puro é aceito.
"""
import json

import pytest
from cryptography.fernet import Fernet

import src.core.criptografia as criptografia
from src.core.criptografia import TokenSemCriptografiaError, impressao_digital_segredo

TOKEN_STREAMER = {"access_token": "STREAMER_ACCESS_abc", "refresh_token": "STREAMER_REFRESH_xyz",
                  "expires_in": 14000, "scope": ["channel:bot"]}
TOKEN_BOT = {"access_token": "BOT_ACCESS_def", "refresh_token": "BOT_REFRESH_uvw",
             "expires_in": 14000, "scope": ["user:write:chat"]}


@pytest.fixture
def dois_tokens(repo):
    repo.new_insert_token(TOKEN_STREAMER, "guild1", "canal", "111", "twitch")
    repo.insert_bot_token(TOKEN_BOT, repo.select_streamer_id("guild1"), "999")


def test_leitura_devolve_o_dicionario_original(repo, dois_tokens):
    assert repo.select_token_by_platform("111") == TOKEN_STREAMER
    assert repo.select_token_by_platform("999") == TOKEN_BOT


def test_banco_guarda_so_o_envelope_cifrado(sql, dois_tokens):
    for (token,) in sql("SELECT token::text FROM streamer_platform"):
        envelope = json.loads(token)
        assert set(envelope) == {"alg", "kid", "ct"}
        assert envelope["alg"] == "fernet" and envelope["kid"] == 1
        assert "ACCESS" not in token and "REFRESH" not in token


def test_refresh_grava_cifrado(repo, sql, dois_tokens):
    novo = dict(TOKEN_STREAMER, access_token="ACCESS_RENOVADO")
    repo.refresh_token(novo, "111")

    assert repo.select_token_by_platform("111") == novo
    assert "RENOVADO" not in sql("SELECT token::text FROM streamer_platform WHERE platform_id = '111'")[0][0]


def test_cifrar_duas_vezes_gera_valores_diferentes():
    # IV aleatório: o mesmo token não produz o mesmo texto cifrado
    assert criptografia.cifrar_token(TOKEN_BOT) != criptografia.cifrar_token(TOKEN_BOT)


def test_app_access_token_filtra_por_validade_sem_decifrar(repo, sql):
    repo.insert_app_access_token({"access_token": "APP_VENCIDO", "expires_in": -100})
    assert repo.select_valid_app_access_token() is None

    repo.insert_app_access_token({"access_token": "APP_VALIDO", "expires_in": 5000000})
    assert repo.select_valid_app_access_token()["access_token"] == "APP_VALIDO"
    assert repo.select_app_access_token()["access_token"] == "APP_VALIDO"

    for (token,) in sql("SELECT token_data::text FROM app_access_token"):
        assert "APP_" not in token


def test_token_em_texto_puro_e_recusado(repo, sql, dois_tokens):
    sql("UPDATE streamer_platform SET token = %s WHERE platform_id = '999'", json.dumps(TOKEN_BOT))

    with pytest.raises(TokenSemCriptografiaError, match="sem criptografia"):
        repo.select_token_by_platform("999")


def test_valor_adulterado_e_recusado(repo, sql, dois_tokens):
    envelope = json.loads(sql("SELECT token::text FROM streamer_platform WHERE platform_id = '111'")[0][0])
    ct = envelope["ct"]
    envelope["ct"] = ct[:-6] + ("A" if ct[-6] != "A" else "B") + ct[-5:]
    sql("UPDATE streamer_platform SET token = %s WHERE platform_id = '111'", json.dumps(envelope))

    with pytest.raises(RuntimeError, match="Não foi possível decifrar"):
        repo.select_token_by_platform("111")


def test_chave_errada_e_recusada(repo, dois_tokens, monkeypatch):
    monkeypatch.setattr(criptografia, "_fernet", Fernet(Fernet.generate_key()))

    with pytest.raises(RuntimeError, match="Não foi possível decifrar"):
        repo.select_token_by_platform("111")


def test_sem_chave_no_env_da_erro_claro(repo, dois_tokens, monkeypatch):
    monkeypatch.setattr(criptografia, "_fernet", None)
    monkeypatch.setitem(criptografia.crypto_config, "TOKEN_ENCRYPTION_KEY", None)

    with pytest.raises(RuntimeError, match="TOKEN_ENCRYPTION_KEY não definida"):
        repo.select_token_by_platform("111")


def test_app_access_token_antigo_em_texto_puro_e_regerado(conn, repo, sql, twitch):
    from src.api.services.auth_service import AuthService

    sql("INSERT INTO app_access_token (token_data, expires_at) VALUES (%s, NOW() + interval '1 day')",
        json.dumps({"access_token": "APP_ANTIGO_PURO"}))

    token = AuthService(conn).get_app_access_token()

    assert token["access_token"].startswith("app-")
    assert repo.select_valid_app_access_token() == token
    assert ("POST", "token", 200) in twitch.chamadas


def test_impressao_digital_identifica_sem_revelar_o_segredo():
    digital = impressao_digital_segredo("meu-segredo-1234567890")

    assert digital.startswith("sha256:")
    assert "meu-segredo" not in digital
    assert digital == impressao_digital_segredo("meu-segredo-1234567890")
    assert digital != impressao_digital_segredo("outro-segredo-1234567890")
