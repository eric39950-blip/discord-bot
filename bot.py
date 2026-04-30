import discord
from discord.ext import commands, tasks
import asyncio
from datetime import datetime
from config import DISCORD_BOT_TOKEN
from database import db
from discord_api import DiscordAPI

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

class PromotionView(discord.ui.View):
    def __init__(self, server_id: str, discord_id: str, new_role: str, xp_required: int):
        super().__init__(timeout=86400)  # 24 horas
        self.server_id = server_id
        self.discord_id = discord_id
        self.new_role = new_role
        self.xp_required = xp_required

    @discord.ui.button(label="✅ Aprovar", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Verificar se o usuário tem permissão de staff
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ Você não tem permissão para aprovar promoções.", ephemeral=True)
            return

        # Promover o usuário
        guild = interaction.guild
        member = guild.get_member(int(self.discord_id))
        if not member:
            await interaction.response.send_message("❌ Usuário não encontrado no servidor.", ephemeral=True)
            return

        config = db.get_config(self.server_id)
        role_id = config.get(f"cargo_{self.new_role}")
        if not role_id:
            await interaction.response.send_message("❌ Cargo de promoção não configurado.", ephemeral=True)
            return

        role = guild.get_role(int(role_id))
        if not role:
            await interaction.response.send_message("❌ Cargo não encontrado.", ephemeral=True)
            return

        try:
            await member.add_roles(role)
            db.update_user_role(self.server_id, self.discord_id, self.new_role)

            # Registrar promoção
            db.add_xp(self.server_id, self.discord_id, 0, "promocao", f"Promovido para {self.new_role}")

            await interaction.response.send_message(f"✅ {member.mention} promovido para {role.mention}!")

            # Desabilitar botões
            for child in self.children:
                child.disabled = True
            await interaction.message.edit(view=self)

        except Exception as e:
            await interaction.response.send_message(f"❌ Erro ao promover: {str(e)}", ephemeral=True)

    @discord.ui.button(label="❌ Rejeitar", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Verificar se o usuário tem permissão de staff
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ Você não tem permissão para rejeitar promoções.", ephemeral=True)
            return

        # Registrar rejeição
        db.add_xp(self.server_id, self.discord_id, 0, "rejeicao", f"Rejeitado para {self.new_role}")

        await interaction.response.send_message(f"❌ Promoção rejeitada para <@{self.discord_id}>.")

        # Desabilitar botões
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")
    print(f"Servidores: {len(bot.guilds)}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    await bot.process_commands(message)

    server_id = str(message.guild.id)
    config = db.get_config(server_id)

    # Verificar se sistema está ativo
    if config.get("sistema_ativo", 1) == 0:
        return

    # Criar ou atualizar usuário
    user = db.create_or_update_user(server_id, str(message.author.id), str(message.author))

    # Verificar cooldown
    cooldown = config.get("cooldown_msg", 60)
    now = int(datetime.now().timestamp())
    if now - user.get("ultimo_xp_msg", 0) < cooldown:
        return

    # Adicionar XP
    xp = config.get("pontos_por_msg", 10)
    db.add_xp(server_id, str(message.author.id), xp, "mensagem")

    # Verificar promoção
    await check_promotion(message.guild, message.author, config)

async def check_promotion(guild: discord.Guild, member: discord.Member, config: dict):
    server_id = str(guild.id)
    user = db.get_user(server_id, str(member.id))
    if not user:
        return

    xp = user["xp"]
    auto_promover = config.get("auto_promover", 1) == 1
    usar_dm = config.get("usar_dm", 1) == 1

    new_role = None
    xp_required = 0

    if xp >= config.get("xp_sargento", 600) and user.get("cargo_atual") != "sargento":
        new_role = "sargento"
        xp_required = config.get("xp_sargento", 600)
    elif xp >= config.get("xp_cabo", 300) and user.get("cargo_atual") != "cabo":
        new_role = "cabo"
        xp_required = config.get("xp_cabo", 300)
    elif xp >= config.get("xp_soldado", 100) and user.get("cargo_atual") != "soldado":
        new_role = "soldado"
        xp_required = config.get("xp_soldado", 100)

    if not new_role:
        return

    if auto_promover:
        # Promoção automática
        role_id = config.get(f"cargo_{new_role}")
        if role_id:
            role = guild.get_role(int(role_id))
            if role:
                try:
                    await member.add_roles(role)
                    db.update_user_role(server_id, str(member.id), new_role)
                    db.add_xp(server_id, str(member.id), 0, "promocao", f"Auto-promovido para {new_role}")

                    if usar_dm:
                        try:
                            await member.send(f"🎉 Parabéns! Você foi promovido para {role.name} no servidor {guild.name}!")
                        except:
                            pass  # Ignorar erro de DM

                except Exception as e:
                    print(f"Erro ao promover {member}: {e}")
    else:
        # Promoção manual - enviar para canal de avaliação
        canal_id = config.get("canal_avaliacao")
        if canal_id:
            channel = guild.get_channel(int(canal_id))
            if channel:
                embed = discord.Embed(
                    title="📈 Solicitação de Promoção",
                    color=discord.Color.blue()
                )
                embed.add_field(name="👤 Usuário", value=member.mention, inline=True)
                embed.add_field(name="🎯 Cargo Solicitado", value=new_role.title(), inline=True)
                embed.add_field(name="⭐ XP Atual", value=f"{xp} XP", inline=True)
                embed.add_field(name="📊 XP Necessário", value=f"{xp_required} XP", inline=True)
                embed.set_footer(text="Staff, use os botões abaixo para aprovar ou rejeitar.")

                view = PromotionView(server_id, str(member.id), new_role, xp_required)
                await channel.send(embed=embed, view=view)

@bot.command(name="xp")
async def cmd_xp(ctx):
    server_id = str(ctx.guild.id)
    user = db.get_user(server_id, str(ctx.author.id))
    if user:
        await ctx.send(f"⭐ Seu XP: {user['xp']}")
    else:
        await ctx.send("❌ Dados não encontrados.")

@bot.command(name="ranking")
async def cmd_ranking(ctx, limit: int = 10):
    server_id = str(ctx.guild.id)
    ranking = db.get_ranking(server_id, limit)
    if not ranking:
        await ctx.send("📊 Nenhum usuário encontrado.")
        return

    embed = discord.Embed(title="🏆 Ranking de XP", color=discord.Color.gold())
    for i, user in enumerate(ranking, 1):
        embed.add_field(
            name=f"{i}. {user['username']}",
            value=f"⭐ {user['xp']} XP",
            inline=False
        )

    await ctx.send(embed=embed)

def run_bot():
    if DISCORD_BOT_TOKEN:
        bot.run(DISCORD_BOT_TOKEN)
    else:
        print("DISCORD_BOT_TOKEN não configurado")