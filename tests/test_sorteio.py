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
    """
    Sem esperas, com prêmio em toda rodada e escolhas previsíveis: random.choice devolve
    sempre a primeira opção (True no sorteio binário; o primeiro candidato, na ordem de
    cadastro, na escolha do espectador).
    """
    from src.bot.services import raffle_service

    async def sem_espera(_segundos):
        return None

    monkeypatch.setattr(raffle_service, "asyncio", types.SimpleNamespace(sleep=sem_espera, to_thread=asyncio.to_thread))
    monkeypatch.setattr(raffle_service, "random", types.SimpleNamespace(choice=lambda opcoes: opcoes[0]))


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



def test_item_sem_resgate_avisa_no_discord_que_volta_a_concorrer(conn, repo, streamer, interacao, chat_twitch):
    """Depois de 3 tentativas sem !claim, o Discord não pode receber o aviso de fim do sorteio."""
    from src.bot.commands.raffle_commands import Raffle
    _cadastrar_item(conn, streamer["guild_id"])
    repo.insert_user(streamer["streamer_id"], "d1", "555", "fulano_discord", "fulano")
    cog = Raffle(bot=None)

    # Ninguém responde. Depois do aviso de item sem ganhador, o criador usa /parar
    def parar_depois_do_aviso(params):
        if params["message_control"] == "not-claim":
            cog.services[streamer["guild_id"]].user_input = False
    chat_twitch.ao_enviar = parar_depois_do_aviso

    _iniciar_sorteio(cog, interacao)

    assert [p["message_control"] for p in chat_twitch.enviadas] == ["claim", "resend_claim"] * 3 + ["not-claim"]
    assert len(interacao.followup.mensagens) == 2, interacao.followup.mensagens
    aviso_item, aviso_fim = interacao.followup.mensagens
    assert "Teclado" in aviso_item and "!claim" in aviso_item
    assert "Itens para sorteio vazio" not in aviso_item
    assert "Itens para sorteio vazio" in aviso_fim


# ---------------------------------------------------------------------------
# Escolha do espectador: sem repetir no mesmo item e com o último ganhador
# fora do item seguinte. As duas regras são preferências: em live com pouca
# gente, afrouxam em vez de travar o sorteio.
# ---------------------------------------------------------------------------

def _cadastrar_itens(conn, guild_id, *nomes):
    """Vários itens no mesmo cadastro (o sorteio só usa o cadastro mais recente)."""
    from src.database.postgres.postgres_repository_raffle import PostgresRepositoryRaffle
    repo = PostgresRepositoryRaffle(conn)
    raffle_id = repo.make_raffle_id(guild_id)
    for nome in nomes:
        repo.insert_items(item=nome, weight=50, raffle_id=raffle_id, guild_id=guild_id)


def _espectadores(repo, streamer, quantidade):
    """Cadastra viewer1, viewer2... e devolve {nome na Twitch: id na Twitch}."""
    ids = {}
    for n in range(1, quantidade + 1):
        repo.insert_user(streamer["streamer_id"], f"d{n}", f"t{n}", f"discord{n}", f"viewer{n}")
        ids[f"viewer{n}"] = f"t{n}"
    return ids


def _chamados(chat):
    """Quem recebeu o pedido de !claim, na ordem."""
    return [p["user_name"] for p in chat.enviadas if p["message_control"] == "claim"]


def _configurar(cog, streamer, chat, redis_teste, ids, responde=lambda vez, nome: False, parar_no_not_claim=True):
    """
    Simula o chat: `responde(vez, nome)` diz se o espectador chamado na vez-ésima
    tentativa (contando todas, a partir de 1) dá !claim. No primeiro item sem ganhador,
    o criador usa /parar, para o laço terminar.
    """
    vezes = []

    def ao_enviar(params):
        if params["message_control"] == "claim":
            vezes.append(params["user_name"])
            if responde(len(vezes), params["user_name"]):
                redis_teste.set(f"claim:twitch:{streamer['platform_id']}:{ids[params['user_name']]}", params["user_name"], ex=17)
        if params["message_control"] == "not-claim" and parar_no_not_claim:
            cog.services[streamer["guild_id"]].user_input = False

    chat.ao_enviar = ao_enviar


def test_tres_tentativas_chamam_tres_pessoas_diferentes(conn, repo, streamer, interacao, chat_twitch, redis_teste):
    from src.bot.commands.raffle_commands import Raffle
    _cadastrar_item(conn, streamer["guild_id"])
    ids = _espectadores(repo, streamer, 3)
    cog = Raffle(bot=None)
    _configurar(cog, streamer, chat_twitch, redis_teste, ids)

    _iniciar_sorteio(cog, interacao)

    assert _chamados(chat_twitch) == ["viewer1", "viewer2", "viewer3"]


def test_com_dois_espectadores_volta_quem_foi_chamado_primeiro(conn, repo, streamer, interacao, chat_twitch, redis_teste):
    from src.bot.commands.raffle_commands import Raffle
    _cadastrar_item(conn, streamer["guild_id"])
    ids = _espectadores(repo, streamer, 2)
    cog = Raffle(bot=None)
    _configurar(cog, streamer, chat_twitch, redis_teste, ids)

    _iniciar_sorteio(cog, interacao)

    assert _chamados(chat_twitch) == ["viewer1", "viewer2", "viewer1"]


def test_com_um_espectador_ele_recebe_as_tres_tentativas(conn, repo, streamer, interacao, chat_twitch, redis_teste):
    from src.bot.commands.raffle_commands import Raffle
    _cadastrar_item(conn, streamer["guild_id"])
    ids = _espectadores(repo, streamer, 1)
    cog = Raffle(bot=None)
    _configurar(cog, streamer, chat_twitch, redis_teste, ids)

    _iniciar_sorteio(cog, interacao)

    assert _chamados(chat_twitch) == ["viewer1", "viewer1", "viewer1"]


def test_ganhador_fica_fora_do_item_seguinte(conn, repo, streamer, interacao, chat_twitch, redis_teste, sql):
    from src.bot.commands.raffle_commands import Raffle
    _cadastrar_itens(conn, streamer["guild_id"], "Teclado", "Mouse")
    ids = _espectadores(repo, streamer, 2)
    cog = Raffle(bot=None)
    _configurar(cog, streamer, chat_twitch, redis_teste, ids, responde=lambda vez, nome: True)

    _iniciar_sorteio(cog, interacao)

    # viewer1 ganha o primeiro item; no segundo, quem é chamado é o viewer2
    assert _chamados(chat_twitch) == ["viewer1", "viewer2"]
    assert sorted(w for (w,) in sql("SELECT winner FROM raffle_items")) == ["discord1", "discord2"]


def test_ultimo_ganhador_volta_antes_de_repetir_alguem_no_item(conn, repo, streamer, interacao, chat_twitch, redis_teste):
    """Conflito das duas regras: sem ninguém novo, libera primeiro o último ganhador."""
    from src.bot.commands.raffle_commands import Raffle
    _cadastrar_itens(conn, streamer["guild_id"], "Teclado", "Mouse")
    ids = _espectadores(repo, streamer, 2)
    cog = Raffle(bot=None)
    # Só a primeira chamada responde: viewer1 ganha o primeiro item, e ninguém responde no segundo
    _configurar(cog, streamer, chat_twitch, redis_teste, ids, responde=lambda vez, nome: vez == 1)

    _iniciar_sorteio(cog, interacao)

    # Item 2: viewer2 (viewer1 acabou de ganhar), depois viewer1 (o último ganhador é
    # liberado antes de repetir alguém) e, sem ninguém novo, o chamado há mais tempo
    assert _chamados(chat_twitch) == ["viewer1", "viewer2", "viewer1", "viewer2"]


def test_bloqueio_do_ganhador_vale_so_durante_o_sorteio(conn, repo, streamer, interacao, chat_twitch, redis_teste):
    """Fica na memória do sorteio: um novo /iniciar_sorteio começa sem bloqueio."""
    from src.bot.commands.raffle_commands import Raffle
    ids = _espectadores(repo, streamer, 2)
    cog = Raffle(bot=None)
    _configurar(cog, streamer, chat_twitch, redis_teste, ids, responde=lambda vez, nome: True)

    _cadastrar_item(conn, streamer["guild_id"], "Teclado")
    _iniciar_sorteio(cog, interacao)
    _cadastrar_item(conn, streamer["guild_id"], "Mouse")
    _iniciar_sorteio(cog, interacao)

    assert _chamados(chat_twitch) == ["viewer1", "viewer1"]


def test_escolha_continua_aleatoria_entre_os_permitidos(conn, repo, streamer, monkeypatch):
    """Com o random de verdade: varia entre os candidatos e nunca pega um bloqueado."""
    import random
    from src.bot.services import raffle_service
    monkeypatch.setattr(raffle_service, "random", random)
    _espectadores(repo, streamer, 3)
    servico = raffle_service.RaffleService(conn, streamer["guild_id"])

    sem_regras = {servico.raffle_viewer([])[0]["discord"]["id"] for _ in range(300)}
    assert sem_regras == {"d1", "d2", "d3"}

    servico.ultimo_ganhador = "d2"
    com_regras = {servico.raffle_viewer(["d1"])[0]["discord"]["id"] for _ in range(300)}
    assert com_regras == {"d3"}
