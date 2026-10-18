import discord
from discord import app_commands
from discord.ext import commands

from src.bot.services.raffle_service import RaffleService, SemEspectadoresError, ItensInvalidosError
from src.database.postgres.connection.postgres_connection import PostgresPool
from src.database.postgres.postgres_repository_raffle import PostgresRepositoryRaffle


# Modal para registrar itens do sorteio
class RegisterRaffleModal(discord.ui.Modal, title="Registrar itens para sorteio"):
    def __init__(self, services):
        super().__init__(title="Registrar itens")
        self.services = services  # Recebe dicionário de serviços por guild

    itens = discord.ui.TextInput(
        label="Itens (item:peso, peso de 1 a 100)",
        placeholder="ex: skin dourada:80, skin prata:30, adesivo (sem peso vale 50)",
        max_length=300,
        style=discord.TextStyle.long
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)

        # Confere o texto antes de abrir conexão: com algum peso inválido, nada é gravado
        try:
            itens_processados = RaffleService.organizar_itens(self.itens.value)
        except ItensInvalidosError as e:
            await interaction.response.send_message(f"Nenhum item foi registrado. {e}")
            return

        conn = PostgresPool.get_conn()
        try:
            repo_raffle = PostgresRepositoryRaffle(conn)
            raffle_id = repo_raffle.make_raffle_id(guild_id)

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

    @app_commands.command(name="registrar_itens", description="Tela para registrar itens para o sorteio")
    async def registrar_itens(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RegisterRaffleModal(self.services))

    @app_commands.command(name="iniciar_sorteio", description="Inicia o loop de sorteio até acabar os itens do sorteio cadastrado ou usuário usar o comando !parar")
    async def iniciar_sorteio(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        if guild_id not in self.services:
            conn = PostgresPool.get_conn()
            try:
                service = RaffleService(conn, guild_id)
                self.services[guild_id] = service

                await interaction.response.send_message("Iniciando sorteio...")

                async def notify_winner(winner_name, item=None):
                    if not winner_name and item:
                        await interaction.followup.send(
                            f"Ninguém deu !claim no item **{item[2]}** após 3 tentativas. "
                            "Ele volta a concorrer nas próximas rodadas."
                        )
                        return
                    if not winner_name:
                        await interaction.followup.send("Itens para sorteio vazio ou usuário parou a função")
                        return
                    await interaction.followup.send(f"🎉 O vencedor foi **{winner_name}** com o item **{item[2]}!**")

                try:
                    await service.raffle_loop(10, notify_winner)
                except SemEspectadoresError:
                    print("[Sorteio] Encerrado: nenhum espectador autenticado")
                    await interaction.followup.send(
                        "Nenhum espectador autenticado neste servidor. "
                        "Peça para os espectadores usarem **!autenticar** e inicie o sorteio de novo."
                    )

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

    @app_commands.command(name="autenticar_plataformas", description="Autenticação primária das plataformas de streams")
    async def autenticar_streamer(self, interaction: discord.Interaction):

        service = RaffleService()
        guild_id = str(interaction.guild.id)
        auth_urls = service.streamer_auth_method(guild_id)
        embed = discord.Embed(title="Autenticar Streamer", description="Comando para fazer a autenticação inicial das plataformas de streaming do streamer")
        embed.set_thumbnail(url="https://i.imgur.com/ZuVOd1O.jpeg")

        embed1 = discord.Embed(title="Autenticação na Twitch", url=f"{auth_urls['twitch']}", description="Clique em **Autenticação na Twitch** para iniciar o processo de autenticação na plataforma.")
        embed1.set_image(url="https://i.imgur.com/1z9lJdj.png")

        embed2 = discord.Embed(title="Autenticação do Bot", url=f"{auth_urls['twitch_bot']}", description="Abra este **logado na Twitch com a conta do bot**. É o que permite o bot falar no chat.")

        # Envia os embeds juntos na mesma mensagem
        await interaction.response.send_message(embeds=[embed, embed1, embed2])

    @commands.command(name="autenticar", description= "Comando para o viewer se autenticar para o sorteios na plataforma que ele desejar")
    async def autenticar_viewer(self, ctx : commands.Context):
        service = RaffleService()
        guild_id = str(ctx.guild.id)
        discord_user_id = str(ctx.author.id)
        discord_user_name = str(ctx.author.name)
        auth_urls = service.viewer_auth_method(guild_id, discord_user_id, discord_user_name)

        embed = discord.Embed(title="Autenticar Viewer", description="Comando para fazer a autenticação inicial das plataformas de streaming do viewer")
        embed.set_thumbnail(url="https://i.imgur.com/ZuVOd1O.jpeg")

        embed1 = discord.Embed(title="Autenticação na Twitch", url=f"{auth_urls['twitch']}", description="Clique em **Autenticação na Twitch** para iniciar o processo de autenticação na plataforma.")
        embed1.set_image(url="https://i.imgur.com/1z9lJdj.png")

        await  ctx.send(embeds=[embed,embed1])

# Setup para carregar o Cog
async def setup(bot):
    await bot.add_cog(Raffle(bot))
