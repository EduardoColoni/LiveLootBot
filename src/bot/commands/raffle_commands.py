import base64

import discord
from discord import app_commands
from discord.app_commands import guilds
from discord.ext import commands
import pkce

from src.bot.services.raffle_service import RaffleService
from src.database.postgres.connection.postgres_connection import PostgresPool
from src.database.redis.redis_repository import RedisRepository
from src.database.redis.connection.redis_connection import RedisConnectionHandle
from src.database.postgres.postgres_repository_raffle import PostgresRepositoryRaffle
from src.core.config import twitch

import uuid
import urllib.parse

# Modal para registrar itens do sorteio
class RegisterRaffleModal(discord.ui.Modal, title="Registrar itens para sorteio"):
    def __init__(self, services):
        super().__init__(title="Registrar itens")
        self.services = services  # Recebe dicionário de serviços por guild

    itens = discord.ui.TextInput(
        label="Adicione itens(item1:peso1, item2:peso2, etc)",
        placeholder="ex: skin dourada:50, skin prata:30",
        max_length=300,
        style=discord.TextStyle.long
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        conn = PostgresPool.get_conn()
        try:
            repo_raffle = PostgresRepositoryRaffle(conn)
            # Usa o serviço do sorteio se já existir, senão cria temporário
            if guild_id in self.services:
                service = self.services[guild_id]
            else:
                service = RaffleService(conn, guild_id)

            raffle_id = repo_raffle.make_raffle_id(guild_id)
            itens_bruto = self.itens.value
            itens_processados = service.organizar_itens(itens_bruto)

            for item, peso in itens_processados:
                repo_raffle.insert_items(item=item, weight=peso, raffle_id=raffle_id, guild_id=guild_id)

            await interaction.response.send_message("Itens registrados com sucesso!")

        except Exception as e:
            await interaction.response.send_message(
                f"Erro ao inserir os itens, verifique a formatação!\nErro: {e}"
            )
            conn.rollback()
        finally:
            PostgresPool.release_conn(conn)

# Cog com os comandos do bot
class Raffle(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.services = {}  # guarda RaffleService por guild_id

    @app_commands.command(name="iniciar", description="Inicia autenticação Twitch")
    async def ola(self, interaction: discord.Interaction):
        redis_conn = RedisConnectionHandle().connect()
        redis_repository = RedisRepository(redis_conn)

        guild_id = str(interaction.guild.id)
        csrf = str(uuid.uuid4())
        state = f"{guild_id}:{csrf}"
        encoded_state = urllib.parse.quote_plus(state)

        redis_repository.insert_ex(f"oauth_state:{csrf}", guild_id, 300)

        auth_url = (
            "https://id.twitch.tv/oauth2/authorize?"
            "response_type=code&"
            "client_id=qamgu47p8wl6qio8fa2ef3e37q3eu2&"
            "redirect_uri=https%3A%2F%2Fremarkably-knowing-serval.ngrok-free.app%2Ftwitch_callback&"
            "scope=moderator%3Aread%3Achatters+chat:edit+chat:read&"
            f"state={encoded_state}"
        )

        await interaction.response.send_message(
            f"Olá, {interaction.user.name}, clique para autenticar: {auth_url}",
            ephemeral=True
        )

    @app_commands.command(name="registrar_sorteio", description="Abre modal para registrar itens")
    async def registrar_sorteio(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RegisterRaffleModal(self.services))

    @app_commands.command()
    async def iniciar_sorteio(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        if guild_id not in self.services:
            conn = PostgresPool.get_conn()
            try:
                service = RaffleService(conn, guild_id)
                self.services[guild_id] = service

                await interaction.response.send_message("Iniciando sorteio...")

                async def notify_winner(winner_name, item=None):
                    if not winner_name:
                        await interaction.followup.send("Itens para sorteio vazio ou usuário parou a função")
                        return
                    await interaction.followup.send(f"🎉 O vencedor foi **{winner_name}** com o item **{item[3]}!**")

                await service.raffle_loop(10, notify_winner)

            finally:
                PostgresPool.release_conn(conn)
                if guild_id in self.services:  # remove instância ao terminar
                    del self.services[guild_id]
        else:
            await interaction.response.send_message("Sorteio já em execução nesse servidor.")

    @app_commands.command()
    async def parar(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        if guild_id in self.services:
            service = self.services[guild_id]
            service.user_input = False
            del self.services[guild_id]  # libera slot imediatamente
            await interaction.response.send_message("Sorteio parado!")
        else:
            await interaction.response.send_message("Nenhum sorteio em execução nesse servidor.")

    @app_commands.command()
    async def teste(self, interaction: discord.Interaction):

        service = RaffleService()
        guild_id = str(interaction.guild.id)
        twitch_auth_url, kick_auth_url = service.auth_method(guild_id)
        embed = discord.Embed(title="Teste", description="abc")
        embed.set_thumbnail(url="https://i.imgur.com/ZuVOd1O.jpeg")

        embed1 = discord.Embed(title="Primeira Imagem", url=f"{twitch_auth_url}", description="Descrição da primeira imagem.")
        embed1.set_image(url="https://i.imgur.com/1z9lJdj.png")

        # Embed 2
        embed2 = discord.Embed(title="Segunda Imagem", url=f"{kick_auth_url}" , description="Descrição da segunda imagem.")
        embed2.set_image(url="https://i.imgur.com/tBQpntA.png")

        # Envia os embeds juntos na mesma mensagem
        await interaction.response.send_message(embeds=[embed,embed1, embed2])


# Setup para carregar o Cog
async def setup(bot):
    await bot.add_cog(Raffle(bot))
