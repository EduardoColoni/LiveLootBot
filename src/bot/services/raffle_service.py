import random
import asyncio
import re
from functools import partial

from src.core.config import kick
from src.core.config import twitch

import uuid
import urllib.parse
import pkce
import json, base64
import requests
from anyio import sleep
from src.core.config import api_config

from src.database.redis.redis_repository import RedisRepository
from src.database.redis.connection.redis_connection import RedisConnectionHandle
from src.database.postgres.postgres_repository_raffle import PostgresRepositoryRaffle
from src.database.postgres.connection.postgres_connection import PostgresPool

class RaffleService:
    def __init__(self, conn=None, guild_id=None):
        self.guild_id = guild_id
        self.conn = conn
        self.repo_raffle = PostgresRepositoryRaffle(self.conn)
        self.redis_conn = RedisConnectionHandle().connect()
        self.user_input = True

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
                print("Itens para sorteio vazio ou usuário parou a função")
                break

            # Decide aleatoriamente se haverá sorteio
            if random.choice([True, False]):
                winner_resolved = False
                attempt = 0

                # Tenta até 3 vezes para que alguém dê claim
                while not winner_resolved and attempt < 3:
                    winner_resolved, viewer, streamer_id, item_name = await self.make_raffle_bot(item, on_winner_callback)
                    attempt += 1

                if not winner_resolved:
                    # Se ninguém deu claim após 3 tentativas, envia aviso e passa para próximo item
                    print("Nenhum vencedor válido encontrado após 3 tentativas")
                    self.send_winner_message(viewer, streamer_id, item_name, "not-claim")

                    await on_winner_callback(None)

            else:
                print("Não haverá sorteio nesse turno")

    async def make_raffle_bot(self, item, on_winner_callback):
        """
        Realiza o sorteio de um item:
        - Seleciona um usuário aleatório
        - Envia mensagem de claim
        - Espera 60s
        - Verifica no Redis se o usuário deu claim
        - Retorna (ganhou: bool, platform_id, winner_name, item_name)
        """

        redis_repository = RedisRepository(self.redis_conn)

        #tudo começa aqui, pego o nome do ganhador
        viewer, streamer_id = await asyncio.to_thread(partial(self.raffle_viewer))
        item_name = str(item[2])



        self.send_winner_message(viewer, streamer_id, item_name, "claim")

        # Aguarda 60 segundos para o usuário dar claim
        await asyncio.sleep(10)

        user_claim = self.get_redis_key(viewer)

        if user_claim is None:
            await asyncio.sleep(5)
            self.send_winner_message(viewer, streamer_id, item_name, "resend_claim")
            # Retorna False mas também os dados do item/vencedor
            return False, viewer, streamer_id, item_name

        # Usuário deu claim, atualiza item
        self.update_item(viewer['discord']['user_name'], item[0], item[1])

        # Envia mensagem de confirmação de claim
        self.send_winner_message(viewer, streamer_id, item_name, "winner")

        # Chama callback passando vencedor e item
        await on_winner_callback(viewer['discord']['user_name'], item)
        return True, viewer, streamer_id, item_name

    def raffle_viewer(self):
        streamer_id = self.repo_raffle.get_streamer_id(self.guild_id)
        raffle_user = self.repo_raffle.raffle_viewer(streamer_id)

        if not raffle_user:
            return None
        else:
            return raffle_user, streamer_id

    def send_message_to_api(self, platform_name: str, platform_id: str, viewer_data: dict, item_name: str, message_control: str):
        url_base = api_config["URL_BASE"]

        # Mapeia a plataforma para o endpoint correto
        platform_endpoint = {
            "twitch": "twitch_chatters/send_message",
            "kick": "kick_chatters/send_message"
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
        print(f"Verificando plataformas do ganhador {viewer}...")

        streamer_platform_id_raw = self.repo_raffle.select_streamer_platforms(streamer_id)

        # 1. Envia para Twitch, se o ganhador estiver cadastrado
        if viewer['twitch']['id'] is not None:
            try:
                print("Ganhador tem cadastro na Twitch. Enviando mensagem...")
                self.send_message_to_api("twitch", streamer_platform_id_raw['twitch']['platform_id'], viewer['twitch'], item_name, message_control)
            except RuntimeError as e:
                print(f"Falha ao enviar mensagem para Twitch: {e}")

        # 2. Envia para Kick, se o ganhador estiver cadastrado
        if viewer['kick']['id'] is not None:
            try:
                print("Ganhador tem cadastro na Kick. Enviando mensagem...")
                self.send_message_to_api("kick", streamer_platform_id_raw['kick']['platform_id'], viewer['kick'], item_name, message_control)
            except RuntimeError as e:
                print(f"Falha ao enviar mensagem para Kick: {e}")

    def get_redis_key(self, viewer: dict):
        redis_repository = RedisRepository(self.redis_conn)
        print(f"Verificando plataformas do ganhador {viewer}...")
        try:
            # 1. Envia para Twitch, se o ganhador estiver cadastrado
            if viewer['twitch']['id'] is not None:
                try:
                    redis_twitch_key = f"{viewer['twitch']['id']};{viewer['twitch']['user_name']}"
                    user_claim_twitch = redis_repository.get(redis_twitch_key)
                    return user_claim_twitch
                except RuntimeError as e:
                    print(f"Falha ao pegar o usuário no redis da twitch: {e}")

        except:
            # 2. Envia para Kick, se o ganhador estiver cadastrado
            if viewer['kick']['id'] is not None:
                try:
                    redis_kick_key = f"{viewer['kick']['id']};{viewer['kick']['user_name']}"
                    user_claim_kick = redis_repository.get(redis_kick_key)
                    return user_claim_kick
                except RuntimeError as e:
                    print(f"Falha ao enviar mensagem para Kick: {e}")

    def update_item(self, winner_name: str, item_id: int, raffle_id: int):
        try:
            self.repo_raffle.update_item(winner_name, item_id, raffle_id)
        except Exception as e:
            self.conn.rollback()
            print(f"Falha ao atualizar o item: {item_id} erro: {e}")

    @staticmethod
    def organizar_itens(itens = None):
        try:
            pares = itens.split(",")
            itens_processados = []

            for par in pares:
                par = par.strip()
                if not par:
                    continue

                # Se tiver delimitador, pega nome e peso
                if ":" in par or ";" in par:
                    nome, peso = re.split("[:;]", par, maxsplit=1)
                    nome = nome.strip()
                    peso = peso.strip()
                    # Se peso não for numérico, ignora ou define None
                    peso_valor = int(peso) if peso.isdigit() else None
                    if not nome:
                        continue
                    itens_processados.append((nome, peso_valor))
                else:
                    return

            return itens_processados
        except:
            return("Item não foram dividos por virgula")

    def streamer_auth_method(self, guild_id : str):
        redis_repository = RedisRepository(self.redis_conn)
        csrf = str(uuid.uuid4())
        state = f"{guild_id}:{csrf}"

        state_dict = {
            "guild_id": guild_id,
            "csrf": csrf
        }
        state_json = json.dumps(state_dict)
        encoded_state = urllib.parse.quote_plus(base64.b64encode(state_json.encode()).decode())

        # Gerar PKCE pair
        code_verifier = pkce.generate_code_verifier(length=128)
        code_challenge = pkce.get_code_challenge(code_verifier)

        redis_repository.insert_ex(f"oauth_state:{csrf}", code_verifier, 300)

        twitch_auth_url = (
            twitch["TWITCH_URL"] + "/authorize?"
            "response_type=code&"
            f"client_id={twitch["CLIENT_ID"]}&"
            "redirect_uri=https%3A%2F%2Fremarkably-knowing-serval.ngrok-free.app%2Ftwitch_callback%2Fstreamer&"
            "scope=chat:edit+chat:read+moderator:read:chatters+user:write:chat&"
            f"state={encoded_state}"
        )

        twitch_auth_url_streamer = (
            twitch["TWITCH_URL"] + "/authorize?"
            "response_type=code&"
            f"client_id={twitch['CLIENT_ID']}&"
            "redirect_uri=https%3A%2F%2Fremarkably-knowing-serval.ngrok-free.app%2Ftwitch_callback%2Fstreamer&"
            "scope=channel:bot+moderator:read:chatters&"
            f"state={encoded_state}"
        )

        twitch_auth_url_bot = (
            twitch["TWITCH_URL"] + "/authorize?"
            "response_type=code&"
            f"client_id={twitch['CLIENT_ID']}&"
            "redirect_uri=https%3A%2F%2Fremarkably-knowing-serval.ngrok-free.app%2Ftwitch_callback%2Fstreamer&"
            "scope=chat:read+chat:edit+user:read:chat+user:write:chat+user:bot+moderator:read:chatters&"
            f"state={encoded_state}"
        )

        kick_auth_url = (
            kick["KICK_URL"] + "/authorize?"
            f"response_type=code&" 
            f"client_id={kick["CLIENT_ID_KICK"]}&"
            f"redirect_uri=https%3A%2F%2Fremarkably-knowing-serval.ngrok-free.app%2Fkick_callback%2Fstreamer&"
            f"scope=user:read%20chat:write%20events:subscribe&"
            f"state={encoded_state}&"
            f"code_challenge={code_challenge}&"
            "code_challenge_method=S256"
        )

        return twitch_auth_url_streamer, kick_auth_url

    def viewer_auth_method(self, guild_id : str, discord_user_id : str, discord_user_name : str):
        redis_repository = RedisRepository(self.redis_conn)
        csrf = str(uuid.uuid4())

        state_dict = {
            "guild_id": guild_id,
            "discord_user_id": discord_user_id,
            "discord_user_name": discord_user_name,
            "csrf": csrf
        }
        state_json = json.dumps(state_dict)
        encoded_state = urllib.parse.quote_plus(base64.b64encode(state_json.encode()).decode())

        # Gerar PKCE pair
        code_verifier = pkce.generate_code_verifier(length=128)
        code_challenge = pkce.get_code_challenge(code_verifier)

        redis_repository.insert_ex(f"oauth_state:{csrf}", code_verifier, 300)

        twitch_auth_url = (
            twitch["TWITCH_URL"] + "/authorize?"
            "response_type=code&"
            f"client_id={twitch["CLIENT_ID"]}&"
            "redirect_uri=https%3A%2F%2Fremarkably-knowing-serval.ngrok-free.app%2Ftwitch_callback%2Fviewer&"
            "scope=user:read:email&"
            f"state={encoded_state}"
        )
        kick_auth_url = (
            kick["KICK_URL"] + "/authorize?"
            f"response_type=code&"
            f"client_id={kick["CLIENT_ID_KICK"]}&"
            f"redirect_uri=https%3A%2F%2Fremarkably-knowing-serval.ngrok-free.app%2Fkick_callback%2Fviewer&"
            f"scope=user:read&"
            f"state={encoded_state}&"
            f"code_challenge={code_challenge}&"
            "code_challenge_method=S256"
        )

        return twitch_auth_url, kick_auth_url