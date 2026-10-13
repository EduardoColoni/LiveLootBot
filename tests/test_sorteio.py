"""
Laço do sorteio, executado pelo comando /iniciar_sorteio de verdade.

O Discord é simulado só na interação (as mensagens que o bot responderia);
banco, Redis e o RaffleService são os reais. As esperas do laço e o sorteio
binário (50% de chance de haver prêmio na rodada) são neutralizados para o
teste não depender de sorte nem levar minutos.
"""
import asyncio
import types

import pytest


class Canal:
    """Faz o papel de interaction.response e interaction.followup: só guarda o que o bot mandaria."""
    def __init__(self):
        self.mensagens = []

    async def send_message(self, mensagem, **kwargs):
        self.mensagens.append(mensagem)

    async def send(self, mensagem, **kwargs):
        self.mensagens.append(mensagem)


@pytest.fixture
def interacao(streamer):
    return types.SimpleNamespace(guild=types.SimpleNamespace(id=streamer["guild_id"]), response=Canal(), followup=Canal())


@pytest.fixture
def chat_twitch(monkeypatch):
    """Substitui o envio de mensagens do bot (que iria para a API) e registra o que seria enviado."""
    from src.bot.services import raffle_service

    chat = types.SimpleNamespace(enviadas=[], ao_enviar=None)

    def enviar(_url, params=None, **_kwargs):
        chat.enviadas.append(params)
        if chat.ao_enviar:
            chat.ao_enviar(params)
        return types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: {})

    monkeypatch.setattr(raffle_service, "requests", types.SimpleNamespace(post=enviar, exceptions=raffle_service.requests.exceptions))
    return chat


@pytest.fixture(autouse=True)
def laco_rapido(monkeypatch):
    """Sem esperas e com prêmio em toda rodada."""
    from src.bot.services import raffle_service

    async def sem_espera(_segundos):
        return None

    monkeypatch.setattr(raffle_service, "asyncio", types.SimpleNamespace(sleep=sem_espera, to_thread=asyncio.to_thread))
    monkeypatch.setattr(raffle_service, "random", types.SimpleNamespace(choice=lambda opcoes: True))


def _cadastrar_item(conn, guild_id, nome="Teclado", peso=50):
    from src.database.postgres.postgres_repository_raffle import PostgresRepositoryRaffle
    repo = PostgresRepositoryRaffle(conn)
    repo.insert_items(item=nome, weight=peso, raffle_id=repo.make_raffle_id(guild_id), guild_id=guild_id)


def _iniciar_sorteio(cog, interacao):
    from src.bot.commands.raffle_commands import Raffle
    asyncio.run(Raffle.iniciar_sorteio.callback(cog, interacao))


def test_sorteio_sem_espectador_autenticado_avisa_e_encerra(conn, streamer, interacao, chat_twitch, sql):
    from src.bot.commands.raffle_commands import Raffle
    _cadastrar_item(conn, streamer["guild_id"])
    cog = Raffle(bot=None)

    _iniciar_sorteio(cog, interacao)  # antes: TypeError "cannot unpack non-iterable NoneType"

    assert interacao.response.mensagens == ["Iniciando sorteio..."]
    assert len(interacao.followup.mensagens) == 1, interacao.followup.mensagens
    assert "!autenticar" in interacao.followup.mensagens[0]
    assert chat_twitch.enviadas == [], "não há a quem anunciar: nada deveria ir para o chat da Twitch"
    assert sql("SELECT winner FROM raffle_items") == [(None,)]

    # O servidor fica livre: um novo /iniciar_sorteio roda de novo, em vez de "Sorteio já em execução"
    _iniciar_sorteio(cog, interacao)
    assert interacao.response.mensagens == ["Iniciando sorteio...", "Iniciando sorteio..."]


def test_sorteio_com_espectador_grava_o_ganhador(conn, repo, streamer, interacao, chat_twitch, redis_teste, sql):
    """O caminho normal continua igual: sorteia, pede o !claim, o viewer confirma, grava e anuncia."""
    from src.bot.commands.raffle_commands import Raffle
    _cadastrar_item(conn, streamer["guild_id"])
    repo.insert_user(streamer["streamer_id"], "d1", "555", "fulano_discord", "fulano")

    # Quando o bot pede o !claim no chat, o viewer responde (o webhook gravaria esta chave)
    def viewer_responde(params):
        if params["message_control"] == "claim":
            redis_teste.set(f"claim:twitch:{streamer['platform_id']}:555", "fulano", ex=17)
    chat_twitch.ao_enviar = viewer_responde

    _iniciar_sorteio(Raffle(bot=None), interacao)

    assert sql("SELECT winner FROM raffle_items") == [("fulano_discord",)]
    assert [p["message_control"] for p in chat_twitch.enviadas] == ["claim", "winner"]
    assert any("fulano_discord" in m and "Teclado" in m for m in interacao.followup.mensagens)

