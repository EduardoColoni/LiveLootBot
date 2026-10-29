import discord
from discord import app_commands
from discord.ext import commands

from discord.utils import escape_markdown

from src.bot.services.raffle_service import (
    RaffleService, SemEspectadoresError, ItensInvalidosError,
    RARIDADES, PESO_MINIMO, PESO_MAXIMO, LIMITE_ITENS,
)
from src.database.postgres.connection.postgres_connection import PostgresPool
from src.database.postgres.postgres_repository_raffle import PostgresRepositoryRaffle


# Cadastro de itens: o /registrar_itens abre um painel, visível só para quem rodou o
# comando, que monta a lista item a item. Nada vai para o banco até clicar em Concluir.

DESCRICAO_RARIDADE = {
    "comum": "Sai com mais frequência",
    "raro": "Sai de vez em quando",
    "lendario": "Sai raramente",
}


class AdicionarItemModal(discord.ui.Modal, title="Adicionar item"):
    nome = discord.ui.Label(
        text="Nome do item",
        component=discord.ui.TextInput(placeholder="ex: Skin dourada", max_length=100),
    )
    chance = discord.ui.Label(
        text="Chance de sair",
        description="Itens comuns saem mais vezes que os lendários.",
        component=discord.ui.RadioGroup(options=[
            discord.RadioGroupOption(label=rotulo, value=valor, description=DESCRICAO_RARIDADE[valor],
                                     default=(valor == "comum"))
            for valor, (rotulo, _) in RARIDADES.items()
        ]),
    )
    peso = discord.ui.Label(
        text="Peso personalizado (avançado)",
        description=f"Opcional: número de {PESO_MINIMO} a {PESO_MAXIMO}. Se preenchido, substitui a chance acima.",
        component=discord.ui.TextInput(placeholder="ex: 75", required=False, max_length=10),
    )

    def __init__(self, painel):
        super().__init__()
        self.painel = painel

    async def on_submit(self, interaction: discord.Interaction):
        nome = (self.nome.component.value or "").strip()
        peso_avancado = (self.peso.component.value or "").strip()
        try:
            if not nome:
                raise ItensInvalidosError("O nome do item não pode ficar em branco.")
            if len(self.painel.itens) >= LIMITE_ITENS:
                raise ItensInvalidosError(f"O cadastro já tem o máximo de {LIMITE_ITENS} itens.")
            peso = RaffleService.peso_do_item(self.chance.component.value, peso_avancado)
        except ItensInvalidosError as e:
            await interaction.response.send_message(f"Item não adicionado. {e}", ephemeral=True)
            return

        # Com peso avançado, o painel mostra o número em vez da raridade
        raridade = None if peso_avancado else self.chance.component.value
        self.painel.itens.append({"nome": nome, "peso": peso, "raridade": raridade})
        await interaction.response.edit_message(embed=self.painel.embed(), view=self.painel.atualizar())


class PainelItens(discord.ui.View):
    def __init__(self, guild_id: str):
        # O token da interação vale 15 minutos; o painel expira um pouco antes
        super().__init__(timeout=14 * 60)
        self.guild_id = guild_id
        self.itens = []  # [{"nome", "peso", "raridade" (None quando o peso é avançado)}]
        self.interacao = None  # a do /registrar_itens, para avisar quando o painel expirar
        self.atualizar()

    def _chance(self, item):
        return RARIDADES[item["raridade"]][0] if item["raridade"] else f"peso {item['peso']}"

    def embed(self) -> discord.Embed:
        total = sum(item["peso"] for item in self.itens)
        linhas = [
            f"• **{escape_markdown(item['nome'])}** · {self._chance(item)} · {round(item['peso'] * 100 / total)}%"
            for item in self.itens
        ]
        embed = discord.Embed(
            title="🎁 Itens do sorteio",
            description="\n".join(linhas) or "Nenhum item ainda. Clique em **Adicionar item** para começar.",
            color=0x02FFFD,
        )
        embed.set_footer(text=f"{len(self.itens)}/{LIMITE_ITENS} itens · A porcentagem é a chance de cada item "
                              f"ser o primeiro sorteado. Nada é salvo até você clicar em Concluir.")
        return embed

    def atualizar(self):
        """Ajusta botões e menu à lista atual. Devolve o próprio painel, para o edit_message."""
        self.adicionar.disabled = len(self.itens) >= LIMITE_ITENS
        self.concluir.disabled = not self.itens

        # O Discord não aceita menu sem opções: sem itens, o menu de remoção sai do painel
        self.remove_item(self.remover)
        if self.itens:
            self.remover.options = [
                discord.SelectOption(label=item["nome"], value=str(posicao), description=self._chance(item))
                for posicao, item in enumerate(self.itens)
            ]
            self.add_item(self.remover)
        return self

    @discord.ui.select(placeholder="🗑️ Remover um item", row=0, options=[discord.SelectOption(label="-")])
    async def remover(self, interaction: discord.Interaction, select: discord.ui.Select):
        posicao = int(select.values[0])
        if 0 <= posicao < len(self.itens):
            del self.itens[posicao]
        await interaction.response.edit_message(embed=self.embed(), view=self.atualizar())

    @discord.ui.button(label="Adicionar item", emoji="➕", style=discord.ButtonStyle.primary, row=1)
    async def adicionar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AdicionarItemModal(self))

    @discord.ui.button(label="Concluir", emoji="✅", style=discord.ButtonStyle.success, row=1)
    async def concluir(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.itens:
            await interaction.response.send_message("Adicione pelo menos um item.", ephemeral=True)
            return

        conn = PostgresPool.get_conn()
        try:
            repo_raffle = PostgresRepositoryRaffle(conn)
            # Cada conclusão é um cadastro novo; o sorteio usa sempre o mais recente
            raffle_id = repo_raffle.make_raffle_id(self.guild_id)
            if raffle_id is None:
                await interaction.response.send_message(
                    "Nenhum streamer autenticado neste servidor. Rode /autenticar_plataformas antes.",
                    ephemeral=True)
                return

            for item in self.itens:
                repo_raffle.insert_items(item=item["nome"], weight=item["peso"], raffle_id=raffle_id,
                                         guild_id=self.guild_id)
        except Exception as e:
            conn.rollback()
            await interaction.response.send_message(f"Erro ao gravar os itens: {e}", ephemeral=True)
            return
        finally:
            PostgresPool.release_conn(conn)

        self.stop()
        embed = self.embed()
        embed.title = "✅ Itens registrados"
        embed.set_footer(text=f"{len(self.itens)} itens prontos. Use /iniciar_sorteio para começar.")
        await interaction.response.edit_message(embed=embed, view=None)

    async def on_timeout(self):
        if self.interacao is None:
            return
        try:
            await self.interacao.edit_original_response(
                content="Este painel expirou e nada foi salvo. Rode /registrar_itens de novo.", view=None)
        except discord.HTTPException:
            pass


# Cog com os comandos do bot
class Raffle(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.services = {}  # guarda RaffleService por guild_id

    @app_commands.command(name="registrar_itens", description="Abre o painel para montar a lista de itens do sorteio")
    async def registrar_itens(self, interaction: discord.Interaction):
        painel = PainelItens(str(interaction.guild.id))
        painel.interacao = interaction
        await interaction.response.send_message(embed=painel.embed(), view=painel, ephemeral=True)

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
