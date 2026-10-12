"""
As duas pontas do !claim montam a mesma chave no Redis.

Já houve um bug em que o webhook usava o id do canal e o sorteio usava o id do
viewer: só coincidia quando o viewer era o dono do canal. Aqui o webhook grava
de verdade (requisição assinada) e o RaffleService procura do jeito dele.
"""
from conftest import SEGREDO_WEBHOOK, enviar_evento, mensagem_de_chat


def _viewer(twitch_id, nome="fulano"):
    return {"discord": {"id": "d1", "user_name": nome}, "twitch": {"id": twitch_id, "user_name": nome}}


def test_sorteio_encontra_o_claim_gravado_pelo_webhook(api, conn, streamer):
    from src.bot.services.raffle_service import RaffleService
    servico = RaffleService(conn, streamer["guild_id"])

    chave = servico.claim_key(_viewer("555"), streamer["streamer_id"])
    assert servico.get_redis_key(chave) is None

    enviar_evento(api, SEGREDO_WEBHOOK, "notification",
                  mensagem_de_chat(streamer["platform_id"], "555", "!claim", chatter_name="fulano"))

    assert servico.get_redis_key(chave) == "fulano"


def test_claim_em_outra_live_nao_vale_para_este_sorteio(api, conn, streamer):
    from src.bot.services.raffle_service import RaffleService
    servico = RaffleService(conn, streamer["guild_id"])

    # O mesmo viewer dá !claim no canal 222, mas o sorteio é do canal 111
    enviar_evento(api, SEGREDO_WEBHOOK, "notification", mensagem_de_chat("222", "555", "!claim"))

    assert servico.get_redis_key(servico.claim_key(_viewer("555"), streamer["streamer_id"])) is None


def test_viewer_sem_twitch_nao_tem_chave(conn, streamer):
    from src.bot.services.raffle_service import RaffleService
    servico = RaffleService(conn, streamer["guild_id"])

    assert servico.claim_key(_viewer(None), streamer["streamer_id"]) is None
