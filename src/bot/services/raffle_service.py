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
        self.user_input = True

    async def raffle_loop(self, time_in_seconds: int, on_winner_callback):
        while True:
            await asyncio.sleep(time_in_seconds)

            item = await asyncio.to_thread(partial(self.repo_raffle.make_raffle, self.guild_id))
            if not self.user_input or not item:
                await on_winner_callback(None)
                print("Itens para sorteio vazio ou usuário parou a função")
                break

            if random.choice([True, False]):
                viewer, streamer_id = await asyncio.to_thread(partial(self.raffle_viewer))
                winner_name = str(viewer['twitch']['user_name'])

                item_name = str(item[2])
                self.update_item(winner_name, item[0], item[1])
                print(f"Sorteio feito: {item}, vencedor: {winner_name}")
                url_base = api_config["URL_BASE"]

                self.send_message_twitch(int(streamer_id),winner_name, item_name)
                #response = requests.post(f"{url_base}/send_message/{streamer_id}/{winner_name}/{item_name}")

                # Chama o callback e passa as informações
                await on_winner_callback(winner_name, item)

            else:
                print("Não haverá sorteio nesse turno")

    def raffle_viewer(self):
        streamer_id = self.repo_raffle.get_streamer_id(self.guild_id)
        raffle_user = self.repo_raffle.raffle_viewer(streamer_id)

        if not raffle_user:
            return None
        else:
            return raffle_user, streamer_id

    def send_message_twitch(self, streamer_id: int, user_id: str, item_name: str):
        url_base = api_config["URL_BASE"]

        # Pega as plataformas do streamer
        platform_raw = self.repo_raffle.select_streamer_platforms(streamer_id)
        if not platform_raw or 'twitch' not in platform_raw:
            raise RuntimeError(f"Streamer {streamer_id} não possui plataforma Twitch cadastrada.")

        platform_id = platform_raw['twitch'].get('platform_id')
        if not platform_id:
            raise RuntimeError(f"Streamer {streamer_id} não possui platform_id válido na Twitch.")

        params_message = {
            "platform_id": platform_id,
            "user_id": user_id,
            "item_name": item_name,
        }

        resp = requests.post(f"{url_base}/twitch_chatters/send_message", params=params_message)

        if resp.status_code != 200:
            raise RuntimeError(f"Erro ao enviar a mensagem: {resp.status_code} - {resp.text}")

        return resp.json()

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
        redis_conn = RedisConnectionHandle().connect()
        redis_repository = RedisRepository(redis_conn)
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
            f"scope=user:read&"
            f"state={encoded_state}&"
            f"code_challenge={code_challenge}&"
            "code_challenge_method=S256"
        )

        return twitch_auth_url_streamer, kick_auth_url

    def viewer_auth_method(self, guild_id : str, discord_user_id : str, discord_user_name : str):
        redis_conn = RedisConnectionHandle().connect()
        redis_repository = RedisRepository(redis_conn)
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