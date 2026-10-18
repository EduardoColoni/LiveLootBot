"""
Cadastro de itens (/registrar_itens): peso padrão 50 quando o peso não é informado e
pesos aceitos só de 1 a 100 (tarefa A2).

Os casos saem da regra, não do código: os limites (0, 1, 100, 101), valores que não são
número inteiro e itens sem peso. O formulário é o RegisterRaffleModal de verdade, preenchido
pelo mesmo caminho que o discord.py usa quando o formulário é enviado, e o resultado é
conferido direto no banco. O sorteio do item é o da função make_raffle, sem simulação.
"""
import asyncio
import types

import pytest

from src.bot.services.raffle_service import RaffleService


class Canal:
    """Faz o papel de interaction.response: só guarda o que o bot responderia."""
    def __init__(self):
        self.mensagens = []

    async def send_message(self, mensagem, **kwargs):
        self.mensagens.append(mensagem)


def _enviar_formulario(guild_id, texto):
    """Envia o formulário do /registrar_itens com `texto` e devolve as respostas do bot."""
    from src.bot.commands.raffle_commands import RegisterRaffleModal
    resposta = Canal()

    async def enviar():
        modal = RegisterRaffleModal(services={})
        # O que o discord.py faz ao receber o formulário preenchido
        modal.itens._refresh_state(None, {"value": texto})
        interacao = types.SimpleNamespace(guild=types.SimpleNamespace(id=guild_id), response=resposta)
        await modal.on_submit(interacao)

    asyncio.run(enviar())
    return resposta.mensagens


# ---------------------------------------------------------------------------
# Leitura do texto do formulário
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("texto, esperado", [
    ("Teclado:30, Mouse:70", [("Teclado", 30), ("Mouse", 70)]),
    ("Teclado", [("Teclado", 50)]),
    ("Teclado:", [("Teclado", 50)]),
    ("Teclado, Mouse:80", [("Teclado", 50), ("Mouse", 80)]),
    ("Teclado;20", [("Teclado", 20)]),
    ("  Teclado :  30 ,Mouse:1 ", [("Teclado", 30), ("Mouse", 1)]),
    ("Teclado:1, Mouse:100", [("Teclado", 1), ("Mouse", 100)]),
])
def test_pesos_validos_e_peso_padrao(texto, esperado):
    assert RaffleService.organizar_itens(texto) == esperado


@pytest.mark.parametrize("peso", ["0", "101", "-5", "abc", "10.5", "1000000"])
def test_peso_fora_de_1_a_100_e_recusado(peso):
    from src.bot.services.raffle_service import ItensInvalidosError

    with pytest.raises(ItensInvalidosError) as erro:
        RaffleService.organizar_itens(f"Teclado:{peso}, Mouse:30")

    assert "Teclado" in str(erro.value)
    assert "Mouse" not in str(erro.value)


def test_recusa_aponta_todos_os_itens_invalidos():
    from src.bot.services.raffle_service import ItensInvalidosError

    with pytest.raises(ItensInvalidosError) as erro:
        RaffleService.organizar_itens("Teclado:0, Mouse:30, Monitor:500")

    assert "Teclado" in str(erro.value) and "Monitor" in str(erro.value)
    assert "Mouse" not in str(erro.value)


def test_cadastro_sem_nenhum_item_e_recusado():
    from src.bot.services.raffle_service import ItensInvalidosError

    with pytest.raises(ItensInvalidosError):
        RaffleService.organizar_itens(" , , ")


# ---------------------------------------------------------------------------
# Formulário de verdade e banco
# ---------------------------------------------------------------------------

def test_formulario_grava_o_peso_padrao_no_banco(streamer, sql):
    mensagens = _enviar_formulario(streamer["guild_id"], "Teclado, Mouse:80")

    assert mensagens == ["Itens registrados com sucesso!"]
    assert dict(sql("SELECT item, weight FROM raffle_items")) == {"Teclado": 50, "Mouse": 80}


def test_formulario_com_peso_invalido_nao_grava_nada(streamer, sql):
    mensagens = _enviar_formulario(streamer["guild_id"], "Teclado:0, Mouse:80")

    assert sql("SELECT item FROM raffle_items") == []
    assert len(mensagens) == 1
    assert "Teclado" in mensagens[0] and "1 a 100" in mensagens[0]


def test_item_cadastrado_sem_peso_e_sorteado(conn, streamer):
    """Antes, o item sem peso ficava com peso vazio e a função do banco nunca o escolhia."""
    from src.database.postgres.postgres_repository_raffle import PostgresRepositoryRaffle
    _enviar_formulario(streamer["guild_id"], "Teclado")

    item = PostgresRepositoryRaffle(conn).make_raffle(streamer["guild_id"])

    assert item is not None and item[2] == "Teclado"


def test_item_sem_peso_concorre_como_peso_50(conn, streamer):
    """'A' sem peso e 'B' com peso 50 devem sair na mesma proporção."""
    from src.database.postgres.postgres_repository_raffle import PostgresRepositoryRaffle
    _enviar_formulario(streamer["guild_id"], "A, B:50")
    repo = PostgresRepositoryRaffle(conn)

    sorteados = [repo.make_raffle(streamer["guild_id"])[2] for _ in range(2000)]

    # Com p = 0,5 e 2.000 sorteios, o desvio padrão é ~1,1%: a faixa de 40% a 60% fica a
    # mais de 8 desvios da média, então o teste não falha por azar.
    assert 0.40 < sorteados.count("A") / len(sorteados) < 0.60
