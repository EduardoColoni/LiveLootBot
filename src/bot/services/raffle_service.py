import random
import asyncio
from functools import partial

from src.core.config import twitch

import uuid
import urllib.parse
import json, base64
import requests
from anyio import sleep
from src.core.config import api_config

from src.database.redis.redis_repository import RedisRepository
from src.database.redis.connection.redis_connection import RedisConnectionHandle
from src.database.postgres.postgres_repository_raffle import PostgresRepositoryRaffle
from src.database.postgres.connection.postgres_connection import PostgresPool


class SemEspectadoresError(Exception):
    """Ninguém fez !autenticar no servidor: não há a quem sortear o item."""


class ItensInvalidosError(Exception):
    """O item do painel do /registrar_itens está sem nome ou com peso fora da regra."""


# Chance de cada item no painel do /registrar_itens: a raridade escolhida vira o peso
# gravado no banco. 60/30/10 é a proporção já conferida na make_raffle.
RARIDADES = {
    "comum": ("Comum", 60),
    "raro": ("Raro", 30),
    "lendario": ("Lendário", 10),
}

# Peso avançado, digitado pelo streamer no lugar da raridade
PESO_MINIMO = 1
PESO_MAXIMO = 100

# O menu de remoção do painel mostra no máximo 25 opções (limite do Discord)
LIMITE_ITENS = 25


class RaffleService:
    def __init__(self, conn=None, guild_id=None):
        self.guild_id = guild_id
        self.conn = conn
        self.repo_raffle = PostgresRepositoryRaffle(self.conn)
        self.redis_conn = RedisConnectionHandle().connect()
        self.user_input = True
        # Discord id de quem ganhou o último item: fica fora do item seguinte, se houver
        # outro viewer. Só vive na memória deste sorteio; um novo /iniciar_sorteio começa
        # sem ninguém bloqueado.
        self.ultimo_ganhador = None

    async def raffle_loop(self, time_in_seconds: int, on_winner_callback):
        """
        Loop principal do sorteio:
        - Espera um tempo definido entre sorteios
        - Sorteia um item
        - Escolhe um vencedor aleatório
        - Aguarda 60s para o claim no Redis
        - Se houver claim, atualiza o item e notifica
        - Se não houver claim, tenta re-sorteio até 3 vezes
        """

        while True:
            await asyncio.sleep(time_in_seconds)

            # Pega o próximo item do sorteio
            item = await asyncio.to_thread(partial(self.repo_raffle.make_raffle, self.guild_id))

            if not self.user_input or not item:
                await on_winner_callback(None)
                print("[Sorteio] Encerrado: sem itens restantes ou interrompido com /parar")
                break

            # Decide aleatoriamente se haverá sorteio
            if random.choice([True, False]):
                winner_resolved = False
                attempt = 0
                chamados = []  # discord ids já chamados neste item, na ordem

                # Tenta até 3 vezes para que alguém dê claim
                while not winner_resolved and attempt < 3:
                    winner_resolved, viewer, streamer_id, item_name = await self.make_raffle_bot(item, on_winner_callback, chamados)
                    attempt += 1

                if not winner_resolved:
                    # Se ninguém deu claim após 3 tentativas, envia aviso e passa para próximo item
                    print("[Sorteio] Ninguém deu !claim após 3 tentativas")
                    await asyncio.to_thread(partial(self.send_winner_message, viewer, streamer_id, item_name, "not-claim"))

                    # Sem ganhador, mas com o item: o Discord avisa que ele volta a concorrer
                    await on_winner_callback(None, item)

            else:
                print("[Sorteio] Não haverá sorteio nesse turno")

    async def make_raffle_bot(self, item, on_winner_callback, chamados):
        """
        Realiza o sorteio de um item:
        - Seleciona um usuário aleatório
        - Envia mensagem de claim
        - Espera 60s
        - Verifica no Redis se o usuário deu claim
        - Retorna (ganhou: bool, platform_id, winner_name, item_name)

        `chamados` são os viewers já chamados neste item; quem for escolhido agora
        entra nela.
        """

        redis_repository = RedisRepository(self.redis_conn)

        #tudo começa aqui, pego o nome do ganhador
        viewer, streamer_id = await asyncio.to_thread(partial(self.raffle_viewer, chamados))
        chamados.append(viewer['discord']['id'])
        item_name = str(item[2])

        # A chave vive mais tempo no Redis do que a espera desta rodada, então
        # limpa antes de avisar no chat: senão um claim da rodada anterior
        # contaria como claim desta.
        claim_key = self.claim_key(viewer, streamer_id)
        if claim_key:
            redis_repository.delete(claim_key)

        await asyncio.to_thread(partial(self.send_winner_message, viewer, streamer_id, item_name, "claim"))

        # Aguarda 60 segundos para o usuário dar claim
        await asyncio.sleep(10)

        user_claim = self.get_redis_key(claim_key)

        if user_claim is None:
            await asyncio.sleep(5)
            await asyncio.to_thread(partial(self.send_winner_message, viewer, streamer_id, item_name, "resend_claim"))
            # Retorna False mas também os dados do item/vencedor
            return False, viewer, streamer_id, item_name

        # Usuário deu claim, atualiza item
        self.update_item(viewer['discord']['user_name'], item[0], item[1])
        self.ultimo_ganhador = viewer['discord']['id']

        # Envia mensagem de confirmação de claim
        await asyncio.to_thread(partial(self.send_winner_message, viewer, streamer_id, item_name, "winner"))

        # Chama callback passando vencedor e item
        await on_winner_callback(viewer['discord']['user_name'], item)
        return True, viewer, streamer_id, item_name

    def raffle_viewer(self, chamados=()):
        """
        Escolhe o viewer da tentativa. As regras são preferências, não proibições, para
        o sorteio não travar em live com pouca gente:
        1. alguém ainda não chamado neste item, que não ganhou o último item;
        2. senão, alguém ainda não chamado neste item (libera o último ganhador);
        3. senão, quem foi chamado há mais tempo neste item.
        """
        streamer_id = self.repo_raffle.get_streamer_id(self.guild_id)
        viewers = self.repo_raffle.select_viewers(streamer_id)

        if not viewers:
            raise SemEspectadoresError("Nenhum espectador autenticado neste servidor")

        novos = [v for v in viewers if v['discord']['id'] not in chamados]
        novos_sem_ultimo_ganhador = [v for v in novos if v['discord']['id'] != self.ultimo_ganhador]

        if novos_sem_ultimo_ganhador:
            return random.choice(novos_sem_ultimo_ganhador), streamer_id
        if novos:
            return random.choice(novos), streamer_id

        # Todos já foram chamados neste item: volta quem foi chamado há mais tempo
        mais_antigo = min(viewers, key=lambda v: chamados.index(v['discord']['id']))
        return mais_antigo, streamer_id

    def send_message_to_api(self, platform_name: str, platform_id: str, viewer_data: dict, item_name: str, message_control: str):
        url_base = api_config["URL_BASE"]

        # Mapeia a plataforma para o endpoint correto
        platform_endpoint = {
            "twitch": "twitch_chatters/send_message"
        }.get(platform_name)

        if not platform_endpoint:
            raise ValueError(f"Plataforma '{platform_name}' não suportada.")

        # O viewer_data já contém o 'user_id' e 'user_name'
        viewer_user_name = viewer_data['user_name']

        params_message = {
            "platform_id": platform_id,
            "user_name": viewer_user_name,
            "item_name": item_name,
            "message_control": message_control
        }

        try:
            resp = requests.post(f"{url_base}/{platform_endpoint}", params=params_message)
            resp.raise_for_status()  # Levanta um erro se o status não for 200
            return resp.json()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Erro ao enviar a mensagem para {platform_name}: {resp.status_code} - {resp.text}")

    def send_winner_message(self, viewer: dict, streamer_id: int, item_name: str, message_control: str):
        streamer_platform_id_raw = self.repo_raffle.select_streamer_platforms(streamer_id)

        # 1. Envia para Twitch, se o ganhador estiver cadastrado
        if viewer['twitch']['id'] is not None:
            try:
                self.send_message_to_api("twitch", streamer_platform_id_raw['twitch']['platform_id'], viewer['twitch'], item_name, message_control)
            except RuntimeError as e:
                print(f"[Sorteio] Falha ao enviar mensagem ({message_control}) para a Twitch: {e}")

    def claim_key(self, viewer: dict, streamer_id: int):
        """
        Monta a chave do claim no Redis, do mesmo jeito que o webhook monta.

        Precisa do id do canal e do id do viewer: pode haver mais de uma live
        rodando ao mesmo tempo e o mesmo viewer estar em duas, então só o id do
        viewer não diz em qual canal ele deu claim.

        Para uma plataforma nova, é montar a chave dela do mesmo jeito aqui.
        """
        if viewer['twitch']['id'] is None:
            return None

        streamer_platforms = self.repo_raffle.select_streamer_platforms(streamer_id)
        if not streamer_platforms or 'twitch' not in streamer_platforms:
            print("Streamer sem cadastro na Twitch, não dá para montar a chave do claim")
            return None

        broadcaster_id = streamer_platforms['twitch']['platform_id']
        return f"claim:twitch:{broadcaster_id}:{viewer['twitch']['id']}"

    def get_redis_key(self, claim_key: str):
        if not claim_key:
            return None

        redis_repository = RedisRepository(self.redis_conn)
        try:
            return redis_repository.get(claim_key)
        except Exception as e:
            print(f"Falha ao pegar o claim no redis: {e}")
            return None

    def update_item(self, winner_name: str, item_id: int, raffle_id: int):
        try:
            self.repo_raffle.update_item(winner_name, item_id, raffle_id)
        except Exception as e:
            self.conn.rollback()
            print(f"Falha ao atualizar o item: {item_id} erro: {e}")

    @staticmethod
    def peso_do_item(raridade: str, peso_avancado: str = "") -> int:
        """
        Peso gravado para um item do painel do /registrar_itens.

        O peso avançado, se preenchido, substitui a raridade e precisa ser inteiro de
        PESO_MINIMO a PESO_MAXIMO; senão, vale o peso da raridade (RARIDADES).
        """
        texto = (peso_avancado or "").strip()
        if texto:
            try:
                peso = int(texto)
            except ValueError:
                peso = None
            if peso is None or not PESO_MINIMO <= peso <= PESO_MAXIMO:
                raise ItensInvalidosError(
                    f"O peso avançado precisa ser um número inteiro de {PESO_MINIMO} a {PESO_MAXIMO} "
                    f"(recebido: {texto}). Deixe em branco para usar a chance escolhida."
                )
            return peso

        if raridade not in RARIDADES:
            raise ItensInvalidosError("Escolha a chance do item.")
        return RARIDADES[raridade][1]

    def streamer_auth_method(self, guild_id : str):
        csrf = str(uuid.uuid4())
        state = f"{guild_id}:{csrf}"

        state_dict = {
            "guild_id": guild_id,
            "csrf": csrf
        }
        state_json = json.dumps(state_dict)
        encoded_state = urllib.parse.quote_plus(base64.b64encode(state_json.encode()).decode())

        # O redirect_uri vem do .env: é o mesmo que o callback usa ao trocar o code
        # pelo token (o OAuth exige os dois iguais) e precisa estar cadastrado no
        # app da Twitch, senão ela recusa com redirect_mismatch.
        twitch_auth_url_streamer = (
            twitch["TWITCH_URL"] + "/authorize?"
            "response_type=code&"
            f"client_id={twitch['CLIENT_ID']}&"
            f"redirect_uri={urllib.parse.quote_plus(twitch['REDIRECT_URI_STREAMER'])}&"
            "scope=channel:bot&"
            f"state={encoded_state}"
        )

        twitch_auth_url_bot = (
            twitch["TWITCH_URL"] + "/authorize?"
            "response_type=code&"
            f"client_id={twitch['CLIENT_ID']}&"
            f"redirect_uri={urllib.parse.quote_plus(twitch['REDIRECT_URI_BOT'])}&"
            "scope=chat:read+chat:edit+user:read:chat+user:write:chat+user:bot&"
            f"state={encoded_state}"
        )

        # Um dicionário por plataforma: para adicionar uma nova, basta montar a URL
        # dela acima e acrescentar mais uma chave aqui.
        return {"twitch": twitch_auth_url_streamer, "twitch_bot": twitch_auth_url_bot}

    def viewer_auth_method(self, guild_id : str, discord_user_id : str, discord_user_name : str):
        csrf = str(uuid.uuid4())

        state_dict = {
            "guild_id": guild_id,
            "discord_user_id": discord_user_id,
            "discord_user_name": discord_user_name,
            "csrf": csrf
        }
        state_json = json.dumps(state_dict)
        encoded_state = urllib.parse.quote_plus(base64.b64encode(state_json.encode()).decode())

        twitch_auth_url = (
            twitch["TWITCH_URL"] + "/authorize?"
            "response_type=code&"
            f"client_id={twitch['CLIENT_ID']}&"
            f"redirect_uri={urllib.parse.quote_plus(twitch['REDIRECT_URI_VIEWER'])}&"
            # Sem escopos: o viewer só precisa provar quem é (id e nome), e /helix/users
            # devolve isso sem permissão nenhuma. O e-mail não é usado, então não é pedido.
            "scope=&"
            f"state={encoded_state}"
        )
        # Um dicionário por plataforma: para adicionar uma nova, basta montar a URL
        # dela acima e acrescentar mais uma chave aqui.
        return {"twitch": twitch_auth_url}