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
                    winner_resolved, platform_id, winner_name, item_name = await self.make_raffle(item, on_winner_callback)
                    attempt += 1

                if not winner_resolved:
                    # Se ninguém deu claim após 3 tentativas, envia aviso e passa para próximo item
                    print("Nenhum vencedor válido encontrado após 3 tentativas")
                    self.send_message_twitch(platform_id, winner_name, item_name, message_control="not-claim")
                    await on_winner_callback(None)

            else:
                print("Não haverá sorteio nesse turno")

    async def make_raffle(self, item, on_winner_callback):
        """
        Realiza o sorteio de um item:
        - Seleciona um usuário aleatório
        - Envia mensagem de claim
        - Espera 60s
        - Verifica no Redis se o usuário deu claim
        - Retorna (ganhou: bool, platform_id, winner_name, item_name)
        """

        redis_repository = RedisRepository(self.redis_conn)
        viewer, streamer_id = await asyncio.to_thread(partial(self.raffle_viewer))
        winner_name = str(viewer['twitch']['user_name'])
        item_name = str(item[2])
        platform_id = self.get_platform_id(int(streamer_id))

        # Envia mensagem de claim no chat
        self.send_message_twitch(platform_id, winner_name, item_name, message_control="claim")

        # Aguarda 60 segundos para o usuário dar claim
        await asyncio.sleep(10)

        redis_key = f"{platform_id};{winner_name}"
        user_claim = redis_repository.get(redis_key)

        if user_claim is None:
            await asyncio.sleep(5)
            print(f"{winner_name} não deu claim. Sorteio inválido.")
            self.send_message_twitch(platform_id, winner_name, item_name, message_control="resend_claim")
            # Retorna False mas também os dados do item/vencedor
            return False, platform_id, winner_name, item_name

        # Usuário deu claim, atualiza item
        self.update_item(winner_name, item[0], item[1])
        print(f"Sorteio realizado com sucesso: {item}, vencedor: {winner_name}")

        # Envia mensagem de confirmação de claim
        self.send_message_twitch(platform_id, winner_name, item_name, message_control="winner")

        # Chama callback passando vencedor e item
        await on_winner_callback(winner_name, item)
        return True, platform_id, winner_name, item_name

    def raffle_viewer(self):
        streamer_id = self.repo_raffle.get_streamer_id(self.guild_id)
        raffle_user = self.repo_raffle.raffle_viewer(streamer_id)

        if not raffle_user:
            return None
        else:
            return raffle_user, streamer_id

    def send_message_twitch(self, platform_id : str, user_id: str, item_name: str, message_control : bool):
        url_base = api_config["URL_BASE"]

        params_message = {
            "platform_id": platform_id,
            "user_id": user_id,
            "item_name": item_name,
            "message_control" : message_control
        }

        resp = requests.post(f"{url_base}/twitch_chatters/send_message", params=params_message)

        if resp.status_code != 200:
            raise RuntimeError(f"Erro ao enviar a mensagem: {resp.status_code} - {resp.text}")

        return resp.json()

    def get_platform_id(self, streamer_id : int):
        # Pega as plataformas do streamer
        platform_raw = self.repo_raffle.select_streamer_platforms(streamer_id)
        if not platform_raw or 'twitch' not in platform_raw:
            raise RuntimeError(f"Streamer {streamer_id} não possui plataforma Twitch cadastrada.")

        platform_id = platform_raw['twitch'].get('platform_id')
        if not platform_id:
            raise RuntimeError(f"Streamer {streamer_id} não possui platform_id válido na Twitch.")

        return platform_id

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