"""
Cadastro de itens pelo painel do /registrar_itens: botão "Adicionar item" abre um
formulário com o nome, a chance (Comum, Raro, Lendário) e um peso avançado opcional de
1 a 100; um menu remove itens; "Concluir" grava o cadastro.

O painel e o formulário são os objetos de verdade do discord.py. O formulário é preenchido
pelo mesmo caminho que o discord.py usa ao receber o envio do Discord (Modal._refresh com
os dados no formato da API), e o menu de remoção também (_refresh_state com os valores
escolhidos). O resultado é conferido no que a pessoa vê (o painel) e direto no banco; o
sorteio do item é o da função make_raffle, sem simulação.
"""
import asyncio
import types

import pytest

from src.bot.commands.raffle_commands import AdicionarItemModal, PainelItens, Raffle
from src.bot.services.raffle_service import LIMITE_ITENS, RARIDADES
from src.database.postgres.postgres_repository_raffle import PostgresRepositoryRaffle


class Resposta:
    """Faz o papel de interaction.response: só guarda o que o bot faria."""
    def __init__(self):
        self.mensagens = []
        self.modais = []
        self.edicoes = []

    async def send_message(self, mensagem=None, **kwargs):
        self.mensagens.append((mensagem, kwargs))

    async def send_modal(self, modal):
        self.modais.append(modal)

    async def edit_message(self, **kwargs):
        self.edicoes.append(kwargs)


def _interacao(guild_id):
    return types.SimpleNamespace(guild=types.SimpleNamespace(id=guild_id), response=Resposta())


def _abrir_painel(guild_id):
    """Roda o /registrar_itens e devolve o painel que ele mandou."""
    interacao = _interacao(guild_id)
    asyncio.run(Raffle.registrar_itens.callback(Raffle(bot=None), interacao))
    (_, kwargs), = interacao.response.mensagens
    assert kwargs.get("ephemeral") is True, "o painel deveria aparecer só para quem rodou o comando"
    return kwargs["view"], kwargs["embed"]


def _adicionar(painel, nome, chance="comum", peso=""):
    """Clica em "Adicionar item", preenche o formulário e envia. Devolve a interação do envio."""
    clique = _interacao(painel.guild_id)
    envio = _interacao(painel.guild_id)

    async def fluxo():
        await painel.adicionar.callback(clique)
        (modal,) = clique.response.modais
        # O que o Discord manda ao enviar um formulário com Labels (tipo 18)
        modal._refresh(envio, [
            {"type": 18, "component": {"type": 4, "custom_id": modal.nome.component.custom_id, "value": nome}},
            {"type": 18, "component": {"type": 21, "custom_id": modal.chance.component.custom_id, "value": chance}},
            {"type": 18, "component": {"type": 4, "custom_id": modal.peso.component.custom_id, "value": peso}},
        ], {})
        await modal.on_submit(envio)

    asyncio.run(fluxo())
    return envio


def _painel_mostrado(envio):
    """Texto do painel depois de uma ação que o atualiza."""
    (edicao,) = envio.response.edicoes
    return edicao["embed"].description


def _remover(painel, posicao):
    escolha = _interacao(painel.guild_id)

    async def fluxo():
        painel.remover._refresh_state(escolha, {"values": [str(posicao)]})
        await painel.remover.callback(escolha)

    asyncio.run(fluxo())
    return escolha


def _concluir(painel):
    clique = _interacao(painel.guild_id)
    asyncio.run(painel.concluir.callback(clique))
    return clique


def _itens_no_banco(sql):
    return sql("SELECT raffle_id, item, weight FROM raffle_items ORDER BY id")


# ---------------------------------------------------------------------------
# Painel
# ---------------------------------------------------------------------------

def test_comando_abre_o_painel_vazio(streamer):
    painel, embed = _abrir_painel(streamer["guild_id"])

    assert isinstance(painel, PainelItens)
    assert painel.itens == []
    assert painel.concluir.disabled, "não deveria dar para concluir sem itens"
    assert not painel.adicionar.disabled


def test_item_adicionado_aparece_no_painel_com_a_chance(streamer, sql):
    painel, _ = _abrir_painel(streamer["guild_id"])

    envio = _adicionar(painel, "Skin dourada", "lendario")

    texto = _painel_mostrado(envio)
    assert "Skin dourada" in texto and "Lendário" in texto
    assert not painel.concluir.disabled
    assert _itens_no_banco(sql) == [], "nada vai para o banco antes de concluir"


def test_painel_mostra_a_chance_de_cada_item_em_porcentagem(streamer):
    painel, _ = _abrir_painel(streamer["guild_id"])
    _adicionar(painel, "Teclado", "comum")

    envio = _adicionar(painel, "Monitor", "lendario")

    # Comum (60) e Lendário (10): 60/70 = 86% e 10/70 = 14%
    texto = _painel_mostrado(envio)
    assert "86%" in texto and "14%" in texto


def test_nome_com_markdown_nao_formata_o_painel(streamer):
    painel, _ = _abrir_painel(streamer["guild_id"])

    envio = _adicionar(painel, "**Teclado**", "comum")

    assert "\\*\\*Teclado\\*\\*" in _painel_mostrado(envio)


def test_remover_item_pelo_menu(streamer, sql):
    painel, _ = _abrir_painel(streamer["guild_id"])
    _adicionar(painel, "Teclado", "comum")
    _adicionar(painel, "Mouse", "raro")
    _adicionar(painel, "Monitor", "lendario")

    escolha = _remover(painel, 1)

    texto = _painel_mostrado(escolha)
    assert "Mouse" not in texto and "Teclado" in texto and "Monitor" in texto
    _concluir(painel)
    assert [item for _, item, _ in _itens_no_banco(sql)] == ["Teclado", "Monitor"]


def test_menu_de_remocao_some_quando_nao_ha_itens(streamer):
    painel, _ = _abrir_painel(streamer["guild_id"])
    assert painel.remover not in painel.children

    _adicionar(painel, "Teclado", "comum")
    assert painel.remover in painel.children

    _remover(painel, 0)
    assert painel.remover not in painel.children
    assert painel.concluir.disabled


def test_limite_de_itens_desabilita_o_botao_de_adicionar(streamer):
    painel, _ = _abrir_painel(streamer["guild_id"])

    for i in range(LIMITE_ITENS):
        _adicionar(painel, f"Item {i}", "comum")

    assert len(painel.itens) == LIMITE_ITENS
    assert painel.adicionar.disabled


# ---------------------------------------------------------------------------
# Chance e peso avançado
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("chance, peso", [("comum", 60), ("raro", 30), ("lendario", 10)])
def test_cada_chance_grava_o_seu_peso(streamer, sql, chance, peso):
    painel, _ = _abrir_painel(streamer["guild_id"])
    _adicionar(painel, "Teclado", chance)

    _concluir(painel)

    assert [(item, w) for _, item, w in _itens_no_banco(sql)] == [("Teclado", peso)]


@pytest.mark.parametrize("peso", ["1", "75", "100", " 42 "])
def test_peso_avancado_substitui_a_chance(streamer, sql, peso):
    painel, _ = _abrir_painel(streamer["guild_id"])
    _adicionar(painel, "Teclado", "raro", peso=peso)

    _concluir(painel)

    assert [w for _, _, w in _itens_no_banco(sql)] == [int(peso)]


def test_painel_mostra_o_peso_avancado_no_lugar_da_chance(streamer):
    painel, _ = _abrir_painel(streamer["guild_id"])

    envio = _adicionar(painel, "Teclado", "raro", peso="75")

    texto = _painel_mostrado(envio)
    assert "peso 75" in texto and "Raro" not in texto


@pytest.mark.parametrize("peso", ["0", "101", "-5", "abc", "10.5", "1000"])
def test_peso_avancado_fora_de_1_a_100_e_recusado(streamer, peso):
    painel, _ = _abrir_painel(streamer["guild_id"])
    _adicionar(painel, "Mouse", "comum")

    envio = _adicionar(painel, "Teclado", "comum", peso=peso)

    assert [i["nome"] for i in painel.itens] == ["Mouse"], "o item com peso inválido não deveria entrar"
    assert envio.response.edicoes == []
    ((mensagem, kwargs),) = envio.response.mensagens
    assert "1 a 100" in mensagem and kwargs.get("ephemeral") is True


def test_nome_em_branco_e_recusado(streamer):
    painel, _ = _abrir_painel(streamer["guild_id"])

    envio = _adicionar(painel, "   ", "comum")

    assert painel.itens == []
    assert len(envio.response.mensagens) == 1


# ---------------------------------------------------------------------------
# Concluir: banco e sorteio
# ---------------------------------------------------------------------------

def test_concluir_grava_um_cadastro_novo_e_fecha_o_painel(streamer, sql):
    antigo, _ = _abrir_painel(streamer["guild_id"])
    _adicionar(antigo, "Item antigo", "comum")
    _concluir(antigo)

    painel, _ = _abrir_painel(streamer["guild_id"])
    _adicionar(painel, "Teclado", "comum")
    _adicionar(painel, "Mouse", "raro")
    clique = _concluir(painel)

    assert _itens_no_banco(sql) == [(1, "Item antigo", 60), (2, "Teclado", 60), (2, "Mouse", 30)]
    (edicao,) = clique.response.edicoes
    assert edicao["view"] is None, "o painel deveria fechar depois de concluir"
    assert "registrados" in edicao["embed"].title.lower()


def test_concluir_sem_streamer_no_servidor_avisa_e_nao_grava(sql):
    painel, _ = _abrir_painel("servidor-sem-streamer")
    _adicionar(painel, "Teclado", "comum")

    clique = _concluir(painel)

    assert _itens_no_banco(sql) == []
    ((mensagem, _),) = clique.response.mensagens
    assert "/autenticar_plataformas" in mensagem
    assert clique.response.edicoes == [], "o painel continua aberto, com a lista"


def test_sorteio_usa_os_itens_do_painel(conn, streamer):
    antigo, _ = _abrir_painel(streamer["guild_id"])
    _adicionar(antigo, "Item antigo", "comum")
    _concluir(antigo)
    painel, _ = _abrir_painel(streamer["guild_id"])
    _adicionar(painel, "Teclado", "lendario")
    _concluir(painel)

    item = PostgresRepositoryRaffle(conn).make_raffle(streamer["guild_id"])

    assert item is not None and item[2] == "Teclado"


def test_chances_saem_na_proporcao_no_sorteio(conn, streamer):
    painel, _ = _abrir_painel(streamer["guild_id"])
    for nome, chance in [("Comum", "comum"), ("Raro", "raro"), ("Lendario", "lendario")]:
        _adicionar(painel, nome, chance)
    _concluir(painel)
    repo = PostgresRepositoryRaffle(conn)

    sorteados = [repo.make_raffle(streamer["guild_id"])[2] for _ in range(3000)]

    # Pesos 60/30/10. Com 3.000 sorteios o desvio padrão fica abaixo de 1%: a faixa de
    # ±4 pontos fica a mais de 4 desvios da média, então o teste não falha por azar.
    for nome, peso in [("Comum", 60), ("Raro", 30), ("Lendario", 10)]:
        assert abs(sorteados.count(nome) / len(sorteados) * 100 - peso) < 4, nome


# ---------------------------------------------------------------------------
# Formulário dentro dos limites do Discord
# ---------------------------------------------------------------------------

def test_formulario_respeita_os_limites_do_discord(streamer):
    """O Discord recusa o formulário inteiro se algum limite for passado; aqui não há Discord para avisar."""
    painel, _ = _abrir_painel(streamer["guild_id"])
    dados = AdicionarItemModal(painel).to_dict()

    componentes = dados["components"]
    assert len(componentes) <= 5
    assert len(dados["title"]) <= 45
    for label in componentes:
        assert label["type"] == 18
        assert len(label["label"]) <= 45
        assert len(label.get("description") or "") <= 100

    radio = componentes[1]["component"]
    assert radio["type"] == 21 and 2 <= len(radio["options"]) <= 10
    assert [o["value"] for o in radio["options"]] == list(RARIDADES)
    assert sum(1 for o in radio["options"] if o.get("default")) == 1
    assert all(len(o["label"]) <= 100 and len(o.get("description") or "") <= 100 for o in radio["options"])
