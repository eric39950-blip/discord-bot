import discord
from discord.ext import commands, tasks
import discord.app_commands as app_commands
import asyncio
import re
from datetime import datetime, timedelta
from typing import Optional
from config import DISCORD_BOT_TOKEN, DB_PATH
from database import db
from discord_api import DiscordAPI

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix=None, intents=intents, help_command=None)
BOT_COLOR = discord.Color.red()

ROLE_CONFIG_KEYS = ["cargo_recruta", "cargo_soldado", "cargo_cabo", "cargo_sargento"]
ROLE_SUFFIXES = ["recruta", "soldado", "cabo", "sargento"]

async def send_log(guild: discord.Guild, log_type: str, embed: discord.Embed = None, content: str = None):
    """Envia log para o canal configurado do tipo especificado."""
    try:
        # Mapear tipos de log para campos de config
        type_mapping = {
            "geral": "gerais",
            "xp": "xp",
            "staff": "staff",
            "evento": "eventos",
            "evento_resposta": "eventos",  # Mesmo canal, mas verificar respostas_enabled
            "ticket": "tickets"
        }
        
        config_type = type_mapping.get(log_type, "gerais")
        log_config = db.get_log_config(str(guild.id), config_type)
        
        if not log_config["enabled"]:
            return
        
        # Para evento_resposta, verificar se respostas estão habilitadas
        if log_type == "evento_resposta":
            config = db.get_config(str(guild.id))
            if not config.get("logs_eventos_respostas_enabled", 1):
                return
        
        channel_id = log_config["channel_id"]
        if not channel_id:
            return
        
        channel = guild.get_channel(int(channel_id))
        if not channel:
            return
        
        if embed:
            await channel.send(embed=embed)
        elif content:
            await channel.send(content)
    except Exception as e:
        print(f"Erro ao enviar log {log_type}: {e}")

async def send_dm_notification(member: discord.Member, dm_type: str, embed: discord.Embed = None, content: str = None):
    """Envia notificação por DM se habilitada."""
    try:
        server_id = str(member.guild.id)
        dm_config = db.get_dm_config(server_id)
        
        if not dm_config.get(f"{dm_type}_enabled", 0):
            return
        
        try:
            if embed:
                await member.send(embed=embed)
            elif content:
                await member.send(content)
        except discord.Forbidden:
            # Usuário bloqueou DMs, registrar em log se possível
            try:
                log_embed = discord.Embed(
                    title="DM Bloqueada",
                    description=f"{member.mention} bloqueou DMs. Notificação de {dm_type} não enviada.",
                    color=discord.Color.orange()
                )
                await send_log(member.guild, "geral", embed=log_embed)
            except:
                pass
    except Exception as e:
        print(f"Erro ao enviar DM {dm_type}: {e}")


def parse_role_from_input(guild: discord.Guild, raw_text: str) -> Optional[discord.Role]:
    if not raw_text:
        return None
    role_mention = re.search(r"<@&([0-9]+)>", raw_text)
    if role_mention:
        return guild.get_role(int(role_mention.group(1)))
    role_id_match = re.search(r"\b([0-9]{17,19})\b", raw_text)
    if role_id_match:
        role = guild.get_role(int(role_id_match.group(1)))
        if role:
            return role
    normalized = raw_text.strip().lower()
    for role in guild.roles:
        if role.name.lower() == normalized:
            return role
    return None


def parse_channel_from_input(guild: discord.Guild, raw_text: str) -> Optional[discord.TextChannel]:
    if not raw_text:
        return None
    channel_mention = re.search(r"<#([0-9]+)>", raw_text)
    if channel_mention:
        return guild.get_channel(int(channel_mention.group(1)))
    channel_id_match = re.search(r"\b([0-9]{17,19})\b", raw_text)
    if channel_id_match:
        channel = guild.get_channel(int(channel_id_match.group(1)))
        if isinstance(channel, discord.TextChannel):
            return channel
    normalized = raw_text.strip().lower()
    for channel in guild.text_channels:
        if channel.name.lower() == normalized:
            return channel
    return None


def parse_user_ids_from_text(text: str) -> set[str]:
    ids = set(re.findall(r"<@!?(\d+)>", text))
    raw_ids = re.findall(r"\b(\d{17,19})\b", text)
    ids.update(raw_ids)
    return ids


def parse_confirmed_members(guild: discord.Guild, text: str) -> list[discord.Member]:
    if not text.strip():
        return []

    # Primeiro, extrair IDs de menções e números
    ids = parse_user_ids_from_text(text)
    members = []

    # Adicionar membros por ID
    for id_str in ids:
        member = guild.get_member(int(id_str))
        if member:
            members.append(member)

    # Separar texto por vírgula, espaço, quebra de linha, ponto e vírgula
    separators = re.split(r'[,\s\n;]+', text)
    for part in separators:
        part = part.strip()
        if not part:
            continue

        # Pular se já foi processado como ID
        if re.match(r'^\d{17,19}$', part):
            continue

        # Tentar buscar por nome/display_name case-insensitive
        part_lower = part.lower()
        for member in guild.members:
            if (member.name.lower() == part_lower or
                member.display_name.lower() == part_lower or
                str(member).lower() == part_lower):
                if member not in members:
                    members.append(member)
                break

    # Evitar duplicados
    unique_members = []
    seen_ids = set()
    for member in members:
        if member.id not in seen_ids:
            unique_members.append(member)
            seen_ids.add(member.id)

    return unique_members

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

        # Get role_id from patentes
        patentes = db.get_patentes(self.server_id)
        patente = next((p for p in patentes if p["nome"].lower() == self.new_role.lower()), None)
        if not patente or not patente.get("role_id"):
            await interaction.response.send_message("❌ Cargo de promoção não configurado.", ephemeral=True)
            return

        role_id = patente["role_id"]
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

class LogsView(discord.ui.View):
    def __init__(self, guild_id: str):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    @discord.ui.button(label="🎫 Tickets Abertos", style=discord.ButtonStyle.blurple)
    async def notif_tickets(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
            return
        
        # Alternar notificação para o usuário
        user_id = str(interaction.user.id)
        notif_type = "tickets"
        
        # Aqui você pode salvar no banco (implementar depois se necessário)
        # Por enquanto, confirmar visualmente
        await interaction.response.send_message(
            f"✅ Você será notificado sobre tickets abertos via DM!",
            ephemeral=True
        )
        button.label = "✅ Tickets Abertos"

    @discord.ui.button(label="📈 Promoções", style=discord.ButtonStyle.blurple)
    async def notif_promotions(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
            return
        
        await interaction.response.send_message(
            f"✅ Você será notificado sobre promoções via DM!",
            ephemeral=True
        )

    @discord.ui.button(label="⭐ XP Changes", style=discord.ButtonStyle.blurple)
    async def notif_xp(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
            return
        
        server_id = str(interaction.guild.id)
        config = db.get_config(server_id)
        log_xp = config.get("log_xp", 0)
        config["log_xp"] = 1 if log_xp == 0 else 0
        db.save_config(config)
        
        status = "ativadas" if config["log_xp"] == 1 else "desativadas"
        await interaction.response.send_message(
            f"✅ Notificações de mudanças de XP {status} no canal de logs!",
            ephemeral=True
        )
        button.label = "✅ XP Changes" if config["log_xp"] == 1 else "⭐ XP Changes"

class LogsEventoView(discord.ui.View):
    def __init__(self, guild_id: str):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    async def refresh_message(self, interaction: discord.Interaction):
        config = db.get_config(self.guild_id)
        embed = discord.Embed(
            title="🏆 Sistema de Logs de Eventos",
            description="Logs de eventos configurados neste canal.",
            color=discord.Color.red()
        )
        embed.add_field(name="Canal", value=interaction.channel.mention if interaction.channel else "Canal não encontrado", inline=True)
        embed.add_field(name="Logs de eventos", value="✅ Ligado" if config.get("logs_eventos_enabled", 1) else "❌ Desligado", inline=True)
        embed.add_field(name="Logs de respostas", value="✅ Ligado" if config.get("logs_eventos_respostas_enabled", 1) else "❌ Desligado", inline=True)
        embed.set_footer(text="Logs de criação, edição, cancelamento e resultados de eventos")
        await interaction.message.edit(embed=embed, view=LogsEventoView(self.guild_id))

    @discord.ui.button(label="Ativar logs de eventos", style=discord.ButtonStyle.success)
    async def enable_logs_eventos(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        db.set_log_enabled(self.guild_id, "evento", True)
        await self.refresh_message(interaction)
        await interaction.followup.send("Logs de eventos ativados.", ephemeral=True)

    @discord.ui.button(label="Desativar logs de eventos", style=discord.ButtonStyle.danger)
    async def disable_logs_eventos(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        db.set_log_enabled(self.guild_id, "evento", False)
        await self.refresh_message(interaction)
        await interaction.followup.send("Logs de eventos desativados.", ephemeral=True)

    @discord.ui.button(label="Ativar logs de respostas", style=discord.ButtonStyle.success)
    async def enable_logs_respostas(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        db.set_log_enabled(self.guild_id, "evento_resposta", True)
        await self.refresh_message(interaction)
        await interaction.followup.send("Logs de respostas ativados.", ephemeral=True)

    @discord.ui.button(label="Desativar logs de respostas", style=discord.ButtonStyle.danger)
    async def disable_logs_respostas(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        db.set_log_enabled(self.guild_id, "evento_resposta", False)
        await self.refresh_message(interaction)
        await interaction.followup.send("Logs de respostas desativados.", ephemeral=True)

class LogsGeralView(discord.ui.View):
    def __init__(self, guild_id: str):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    @discord.ui.button(label="📝 Ativar Logs Gerais", style=discord.ButtonStyle.green)
    async def toggle_logs_gerais(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.followup.send("❌ Você não tem permissão.", ephemeral=True)
            return
        
        server_id = str(interaction.guild.id)
        config = db.get_config(server_id)
        new_status = not config.get("logs_gerais_enabled", 1)
        db.set_log_enabled(server_id, "gerais", new_status)
        
        # Atualizar embed
        embed = interaction.message.embeds[0]
        embed.set_field_at(1, name="Logs gerais", value="✅ Ligado" if new_status else "❌ Desligado", inline=True)
        await interaction.edit_original_response(embed=embed)
        await interaction.followup.send("Configuração atualizada.", ephemeral=True)

    @discord.ui.button(label="🚫 Desativar Logs Gerais", style=discord.ButtonStyle.red)
    async def desativar_logs_gerais(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Este botão pode ser removido, pois o toggle faz tudo
        pass

    @discord.ui.button(label="⭐ Ativar Logs XP", style=discord.ButtonStyle.green)
    async def toggle_logs_xp(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.followup.send("❌ Você não tem permissão.", ephemeral=True)
            return
        
        server_id = str(interaction.guild.id)
        config = db.get_config(server_id)
        new_status = not config.get("logs_xp_enabled", 1)
        db.set_log_enabled(server_id, "xp", new_status)
        
        # Atualizar embed
        embed = interaction.message.embeds[0]
        embed.set_field_at(2, name="Logs XP", value="✅ Ligado" if new_status else "❌ Desligado", inline=True)
        await interaction.edit_original_response(embed=embed)
        await interaction.followup.send("Configuração atualizada.", ephemeral=True)

    @discord.ui.button(label="🚫 Desativar Logs XP", style=discord.ButtonStyle.red)
    async def desativar_logs_xp(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="👑 Ativar Logs Staff", style=discord.ButtonStyle.green)
    async def toggle_logs_staff(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.followup.send("❌ Você não tem permissão.", ephemeral=True)
            return
        
        server_id = str(interaction.guild.id)
        config = db.get_config(server_id)
        new_status = not config.get("logs_staff_enabled", 1)
        db.set_log_enabled(server_id, "staff", new_status)
        
        # Atualizar embed
        embed = interaction.message.embeds[0]
        embed.set_field_at(3, name="Logs Staff", value="✅ Ligado" if new_status else "❌ Desligado", inline=True)
        await interaction.edit_original_response(embed=embed)
        await interaction.followup.send("Configuração atualizada.", ephemeral=True)

    @discord.ui.button(label="🚫 Desativar Logs Staff", style=discord.ButtonStyle.red)
    async def desativar_logs_staff(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

class LogsTicketView(discord.ui.View):
    def __init__(self, guild_id: str):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    @discord.ui.button(label="🎫 Ativar Logs Tickets", style=discord.ButtonStyle.green)
    async def toggle_logs_tickets(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.followup.send("❌ Você não tem permissão.", ephemeral=True)
            return
        
        server_id = str(interaction.guild.id)
        config = db.get_config(server_id)
        new_status = not config.get("logs_tickets_enabled", 1)
        db.set_log_enabled(server_id, "tickets", new_status)
        
        # Atualizar embed
        embed = interaction.message.embeds[0]
        embed.set_field_at(1, name="Logs de tickets", value="✅ Ligado" if new_status else "❌ Desligado", inline=True)
        await interaction.edit_original_response(embed=embed)
        await interaction.followup.send("Configuração atualizada.", ephemeral=True)

    @discord.ui.button(label="🚫 Desativar Logs Tickets", style=discord.ButtonStyle.red)
    async def desativar_logs_tickets(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

class DMNotificationsView(discord.ui.View):
    def __init__(self, guild_id: str):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    @discord.ui.button(label="👑 Alternar DM Promoções", style=discord.ButtonStyle.blurple)
    async def toggle_dm_promocoes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.followup.send("❌ Você não tem permissão.", ephemeral=True)
            return
        
        server_id = str(interaction.guild.id)
        dm_config = db.get_dm_config(server_id)
        new_status = not dm_config["promocoes"]
        db.set_dm_enabled(server_id, "promocoes", new_status)
        
        # Atualizar embed
        embed = interaction.message.embeds[0]
        embed.set_field_at(0, name="DM Promoções", value="✅ Ligado" if new_status else "❌ Desligado", inline=True)
        await interaction.edit_original_response(embed=embed)
        await interaction.followup.send("Configuração atualizada.", ephemeral=True)

    @discord.ui.button(label="🏆 Alternar DM Eventos", style=discord.ButtonStyle.blurple)
    async def toggle_dm_eventos(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.followup.send("❌ Você não tem permissão.", ephemeral=True)
            return
        
        server_id = str(interaction.guild.id)
        dm_config = db.get_dm_config(server_id)
        new_status = not dm_config["eventos"]
        db.set_dm_enabled(server_id, "eventos", new_status)
        
        # Atualizar embed
        embed = interaction.message.embeds[0]
        embed.set_field_at(1, name="DM Eventos", value="✅ Ligado" if new_status else "❌ Desligado", inline=True)
        await interaction.edit_original_response(embed=embed)
        await interaction.followup.send("Configuração atualizada.", ephemeral=True)

    @discord.ui.button(label="🎫 Alternar DM Tickets", style=discord.ButtonStyle.blurple)
    async def toggle_dm_tickets(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.followup.send("❌ Você não tem permissão.", ephemeral=True)
            return
        
        server_id = str(interaction.guild.id)
        dm_config = db.get_dm_config(server_id)
        new_status = not dm_config["tickets"]
        db.set_dm_enabled(server_id, "tickets", new_status)
        
        # Atualizar embed
        embed = interaction.message.embeds[0]
        embed.set_field_at(2, name="DM Tickets", value="✅ Ligado" if new_status else "❌ Desligado", inline=True)
        await interaction.edit_original_response(embed=embed)
        await interaction.followup.send("Configuração atualizada.", ephemeral=True)

    @discord.ui.button(label="👮 Alternar DM Staff", style=discord.ButtonStyle.blurple)
    async def toggle_dm_staff(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
            return
        
        server_id = str(interaction.guild.id)
        dm_config = db.get_dm_config(server_id)
        new_status = not dm_config["staff"]
        db.set_dm_enabled(server_id, "staff", new_status)
        
        # Atualizar embed
        embed = interaction.message.embeds[0]
        embed.set_field_at(3, name="DM Staff", value="✅ Ligado" if new_status else "❌ Desligado", inline=True)
        await interaction.response.edit_message(embed=embed)
        await interaction.followup.send("Configuração atualizada.", ephemeral=True)

    @discord.ui.button(label="🚫 Desativar Todas DMs", style=discord.ButtonStyle.red)
    async def desativar_todas_dm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
            return
        
        server_id = str(interaction.guild.id)
        db.disable_all_dm(server_id)
        
        # Atualizar embed
        embed = interaction.message.embeds[0]
        embed.set_field_at(0, name="DM Promoções", value="❌ Desligado", inline=True)
        embed.set_field_at(1, name="DM Eventos", value="❌ Desligado", inline=True)
        embed.set_field_at(2, name="DM Tickets", value="❌ Desligado", inline=True)
        embed.set_field_at(3, name="DM Staff", value="❌ Desligado", inline=True)
        await interaction.response.edit_message(embed=embed)
        await interaction.followup.send("Configuração atualizada.", ephemeral=True)

class TicketView(discord.ui.View):
    @discord.ui.button(label="🎫 Abrir Ticket", style=discord.ButtonStyle.primary)
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user

        # Verificar se já foi verificado
        config = db.get_config(str(guild.id))
        cargo_id = config.get("cargo_verificado")
        if cargo_id:
            role = guild.get_role(int(cargo_id))
            if role and role in user.roles and not user.guild_permissions.administrator:
                await interaction.response.send_message("❌ Você já foi verificado e possui o cargo necessário. Não é possível abrir outro ticket.", ephemeral=True)
                return

        # Verificar se já existe ticket aberto
        existing_ticket = discord.utils.get(guild.channels, name=f"ticket-{user.id}")
        if existing_ticket:
            await interaction.response.send_message("❌ Você já tem um ticket aberto.", ephemeral=True)
            return

        # Criar canal de ticket privado para o usuário
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }

        # Conceder acesso a cargos de staff/admin com permissão de manage_channels
        for role in guild.roles:
            if role.permissions.manage_channels and role != guild.default_role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        category = interaction.channel.category
        channel = await guild.create_text_channel(f"ticket-{user.id}", overwrites=overwrites, category=category)

        embed = discord.Embed(
            title="🎫 Ticket Aberto com Sucesso",
            description=(
                f"Olá {user.mention}, seu ticket foi criado com sucesso. "
                "A equipe de suporte irá analisar sua solicitação e responder o mais breve possível neste canal."
            ),
            color=discord.Color.green()
        )
        embed.add_field(name="Canal", value=channel.mention, inline=False)
        embed.set_footer(text="Apenas você e a equipe autorizada têm acesso a este canal.")

        await channel.send(embed=embed)
        
        # Embed do formulário de verificação
        form_embed = discord.Embed(
            title="📋 Formulário de Verificação",
            description=(
                "Para prosseguir com sua entrada na nossa comunidade, por favor responda com atenção ao formulário abaixo. "
                "Forneça informações verdadeiras e completas para que possamos avaliar sua solicitação adequadamente."
            ),
            color=discord.Color.from_rgb(255, 165, 0)
        )
        
        form_embed.add_field(
            name="🎮 Nickname no Roblox",
            value="( Não Apelido )",
            inline=False
        )
        form_embed.add_field(
            name="👤 Usuário do Discord",
            value="( Não Apelido )",
            inline=False
        )
        form_embed.add_field(
            name="🌍 Nacionalidade",
            value="( De qual País você é )",
            inline=False
        )
        form_embed.add_field(
            name="⚔️ Jura lealdade pela vossa nação?",
            value="( Sim ou não )",
            inline=False
        )
        form_embed.add_field(
            name="💪 Entende que sua atividade é crucial na vossa nação?",
            value="( )",
            inline=False
        )
        form_embed.add_field(
            name="🏷️ Pegou seus cargos selecionáveis",
            value="⁠#cargos-selecionaveis ( Sim )",
            inline=False
        )
        form_embed.add_field(
            name="🎯 Pretende focar na nossa nação",
            value="( Sim, ou se quer ser mercenário, priorizando outras facções ante a nossa )",
            inline=False
        )
        form_embed.add_field(
            name="👥 Solicitou no Grupo",
            value="[Clique aqui](https://www.roblox.com/share/g/35338327)",
            inline=False
        )
        form_embed.set_footer(text="⏰ Por favor, responda com atenção a todos os campos")
        
        await channel.send(embed=form_embed)
        
        # Adicionar botão para copiar o formulário
        view = FormularioView()
        await channel.send("Clique no botão abaixo para copiar o formulário em texto:", view=view)
        
        # Notificar admins sobre novo ticket
        for admin in guild.members:
            if admin.guild_permissions.manage_channels and not admin.bot:
                try:
                    notif_embed = discord.Embed(
                        title="🎫 Novo Ticket Aberto",
                        description=f"{user.mention} abriu um ticket de verificação",
                        color=discord.Color.blue()
                    )
                    notif_embed.add_field(name="Usuário", value=f"{user.name}#{user.discriminator}", inline=False)
                    notif_embed.add_field(name="Canal", value=f"[Ir para o ticket]({channel.jump_url})", inline=False)
                    await admin.send(embed=notif_embed)
                except:
                    pass  # Ignorar erro de DM

        log_embed = discord.Embed(
            title="🎫 Ticket Aberto",
            description=f"{user.mention} abriu um ticket de verificação.",
            color=discord.Color.orange()
        )
        log_embed.add_field(name="Canal", value=f"[Ir para o ticket]({channel.jump_url})", inline=False)
        await send_log(guild, "ticket", embed=log_embed)
        
        await interaction.response.send_message("✅ Ticket criado! Verifique o canal criado.", ephemeral=True)

class FormularioView(discord.ui.View):
    @discord.ui.button(label="📋 Copiar Formulário", style=discord.ButtonStyle.blurple)
    async def copiar_formulario(self, interaction: discord.Interaction, button: discord.ui.Button):
        formulario_texto = """
🎮 Nickname no Roblox (Não Apelido): 
👤 Usuário do Discord (Não Apelido): 
🌍 Nacionalidade (De qual País você é): 
⚔️ Jura lealdade pela vossa nação? (Sim ou não): 
💪 Entende que sua atividade é crucial na vossa nação?: 
🏷️ Pegou seus cargos selecionáveis #cargos-selecionaveis? (Sim): 
🎯 Pretende focar na nossa nação? (Sim ou Mercenário): 
👥 Solicitou no Grupo? https://www.roblox.com/share/g/35338327
        """
        await interaction.response.send_message(f"```\n{formulario_texto}\n```", ephemeral=True)

class EventoConfirmView(discord.ui.View):
    def __init__(self, treino_id: int, server_id: str):
        super().__init__(timeout=None)
        self.treino_id = treino_id
        self.server_id = server_id

    async def refresh_embed(self, message: discord.Message):
        current_embed = message.embeds[0] if message.embeds else None
        if not current_embed:
            return

        embed = discord.Embed(
            title=current_embed.title or "Evento",
            description=current_embed.description or "",
            color=current_embed.color or discord.Color.blue()
        )

        for field in current_embed.fields:
            if field.name in ("Confirmados", "Talvez", "Não vou"):
                continue
            embed.add_field(name=field.name, value=field.value, inline=field.inline)

        respostas = db.get_treino_respostas(self.treino_id)
        count_vou = sum(1 for r in respostas if r["resposta"] == "vou")
        count_talvez = sum(1 for r in respostas if r["resposta"] == "talvez")
        count_nao = sum(1 for r in respostas if r["resposta"] == "nao")

        embed.add_field(name="Confirmados", value=str(count_vou), inline=True)
        embed.add_field(name="Talvez", value=str(count_talvez), inline=True)
        embed.add_field(name="Não vou", value=str(count_nao), inline=True)

        try:
            await message.edit(embed=embed, view=self)
        except Exception:
            pass

    async def update_respostas_log(self, interaction: discord.Interaction):
        config = db.get_config(self.server_id)
        if not config.get("logs_eventos_enabled", 1) or not config.get("logs_eventos_respostas_enabled", 1):
            return

        treino = db.get_treino(self.treino_id)
        respostas = db.get_treino_respostas(self.treino_id)

        vou_users = [r for r in respostas if r["resposta"] == "vou"]
        talvez_users = [r for r in respostas if r["resposta"] == "talvez"]
        nao_users = [r for r in respostas if r["resposta"] == "nao"]

        embed = discord.Embed(
            title="📋 Respostas do Evento",
            color=discord.Color.red()
        )
        embed.add_field(name="Evento", value=treino.get("titulo", treino.get("descricao", "Sem título")), inline=False)
        embed.add_field(name="ID do Evento", value=str(self.treino_id), inline=True)
        embed.add_field(name="Data/Hora", value=treino.get("horario_inicio", "Não definido"), inline=True)
        embed.add_field(name="Canal", value=f"<#{treino.get('canal_id')}>" if treino.get('canal_id') else "Não definido", inline=True)

        vou_list = "\n".join([f"<@{r['discord_id']}>" for r in vou_users]) if vou_users else "Nenhum"
        embed.add_field(name="✅ Vão", value=vou_list, inline=False)

        talvez_list = "\n".join([f"<@{r['discord_id']}>" for r in talvez_users]) if talvez_users else "Nenhum"
        embed.add_field(name="❔ Talvez", value=talvez_list, inline=False)

        nao_list = "\n".join([f"<@{r['discord_id']}>" for r in nao_users]) if nao_users else "Nenhum"
        embed.add_field(name="❌ Não vão", value=nao_list, inline=False)

        embed.set_footer(text=f"Última atualização: {datetime.now().strftime('%d/%m/%Y %H:%M')}")

        # Enviar ou editar mensagem de log
        log_message_id = treino.get("logs_respostas_message_id")
        log_channel_id = config.get("logs_eventos_channel_id")
        if not log_channel_id:
            return

        log_channel = interaction.guild.get_channel(int(log_channel_id)) if log_channel_id else None
        if log_message_id and log_channel:
            try:
                message = await log_channel.fetch_message(int(log_message_id))
                await message.edit(embed=embed)
                return
            except Exception:
                pass

        if log_channel:
            message = await log_channel.send(embed=embed)
            db.update_treino_logs_respostas_message_id(self.treino_id, str(message.id))

    @discord.ui.button(label="✅ Vou", style=discord.ButtonStyle.success)
    async def confirm_vou(self, interaction: discord.Interaction, button: discord.ui.Button):
        treino = db.get_treino(self.treino_id)
        if treino.get("status") == "finalizado":
            await interaction.response.send_message("Este evento já foi finalizado e não aceita novas respostas.", ephemeral=True)
            return
        discord_id = str(interaction.user.id)
        existing = db.get_treino_resposta(self.treino_id, discord_id)
        if existing and existing.get("resposta") == "vou":
            await interaction.response.send_message("✅ Sua resposta já está registrada como Vou!", ephemeral=True)
            return

        db.set_treino_resposta(self.treino_id, self.server_id, discord_id, "vou")
        db.create_or_update_user(self.server_id, discord_id, str(interaction.user))
        db.update_last_activity(self.server_id, discord_id)
        await self.refresh_embed(interaction.message)
        await self.update_respostas_log(interaction)
        
        await interaction.response.send_message("✅ Resposta registrada: Vou! Seu XP será concedido apenas no resultado do evento.", ephemeral=True)

    @discord.ui.button(label="🤔 Talvez", style=discord.ButtonStyle.secondary)
    async def confirm_talvez(self, interaction: discord.Interaction, button: discord.ui.Button):
        treino = db.get_treino(self.treino_id)
        if treino.get("status") == "finalizado":
            await interaction.response.send_message("Este evento já foi finalizado e não aceita novas respostas.", ephemeral=True)
            return
        discord_id = str(interaction.user.id)
        existing = db.get_treino_resposta(self.treino_id, discord_id)
        if existing and existing.get("resposta") == "talvez":
            await interaction.response.send_message("🤔 Sua resposta já está registrada como Talvez!", ephemeral=True)
            return

        db.set_treino_resposta(self.treino_id, self.server_id, discord_id, "talvez")
        db.create_or_update_user(self.server_id, discord_id, str(interaction.user))
        db.update_last_activity(self.server_id, discord_id)
        await self.refresh_embed(interaction.message)
        await self.update_respostas_log(interaction)
        
        await interaction.response.send_message("🤔 Resposta registrada: Talvez! Seu XP será concedido apenas no resultado do evento.", ephemeral=True)

    @discord.ui.button(label="❌ Não vou", style=discord.ButtonStyle.danger)
    async def confirm_nao(self, interaction: discord.Interaction, button: discord.ui.Button):
        treino = db.get_treino(self.treino_id)
        if treino.get("status") == "finalizado":
            await interaction.response.send_message("Este evento já foi finalizado e não aceita novas respostas.", ephemeral=True)
            return
        discord_id = str(interaction.user.id)
        existing = db.get_treino_resposta(self.treino_id, discord_id)
        if existing and existing.get("resposta") == "nao":
            await interaction.response.send_message("❌ Sua resposta já está registrada como Não vou!", ephemeral=True)
            return

        db.set_treino_resposta(self.treino_id, self.server_id, discord_id, "nao")
        db.create_or_update_user(self.server_id, discord_id, str(interaction.user))
        db.update_last_activity(self.server_id, discord_id)
        await self.refresh_embed(interaction.message)
        await self.update_respostas_log(interaction)
        
        await interaction.response.send_message("❌ Resposta registrada: Não vou! Seu XP será concedido apenas no resultado do evento.", ephemeral=True)

@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")
    print(f"Servidores: {len(bot.guilds)}")
    
    # Debug prints for each server
    for guild in bot.guilds:
        server_id = str(guild.id)
        print(f"DATABASE_PATH: {DB_PATH}")
        config = db.get_config(server_id)
        print(f"Config carregada para {guild.name}: {config}")
        
        # Ensure default patentes and canais
        db.ensure_default_patentes(server_id)
        db.ensure_default_canais(server_id)
        
        patentes = db.get_patentes(server_id)
        print(f"Patentes carregadas para {guild.name}: {patentes}")
        canais = db.get_config_canais(server_id)
        print(f"Canais configurados para {guild.name}: {canais}")
    
    await bot.tree.sync()

    # Iniciar task de lembretes e monitor de inatividade
    lembrete_task.start()
    inactivity_task.start()

    # Resend setup embeds if configured channels exist
    for guild in bot.guilds:
        server_id = str(guild.id)
        config = db.get_config(server_id)
        
        # Resend ticket setup if canal_avaliacao is configured
        if config.get("canal_avaliacao"):
            try:
                channel = guild.get_channel(int(config["canal_avaliacao"]))
                if channel:
                    embed = discord.Embed(
                        title="🎫 Atendimento de Suporte",
                        description=(
                            "Abra um ticket para registrar sua solicitação de verificação ou suporte. "
                            "A equipe irá analisar sua solicitação neste canal com atenção e retornará o mais breve possível."
                        ),
                        color=discord.Color.blue()
                    )
                    embed.add_field(
                        name="Como funciona",
                        value=(
                            "1. Clique em 'Abrir Ticket' para criar um canal privado.\n"
                            "2. Responda ao formulário de verificação com informações verdadeiras.\n"
                            "3. A equipe irá revisar sua solicitação. Staff usará reações para aprovar ou rejeitar."
                        ),
                        inline=False
                    )
                    embed.add_field(
                        name="Avaliação",
                        value=(
                            "✅ Aprovar — o usuário receberá o cargo configurado de verificado.\n"
                            "❌ Rejeitar — o usuário não receberá o cargo e será informado da recusa."
                        ),
                        inline=False
                    )
                    embed.set_footer(text="Apenas staff autorizado pode abrir, analisar e responder tickets.")

                    view = TicketView()
                    await channel.send(embed=embed, view=view)
            except Exception as e:
                print(f"Erro ao reenviar setup de tickets para {guild.name}: {e}")
        
        # Resend logs setup if canal_logs is configured
        if config.get("canal_logs"):
            try:
                channel = guild.get_channel(int(config["canal_logs"]))
                if channel:
                    embed = discord.Embed(
                        title="🔔 Sistema de Notificações",
                        description="Clique nos botões abaixo para ativar notificações via DM sobre eventos do servidor.",
                        color=discord.Color.from_rgb(255, 165, 0)
                    )
                    embed.add_field(
                        name="🎫 Tickets Abertos",
                        value="Receba notificação quando um novo ticket for aberto",
                        inline=False
                    )
                    embed.add_field(
                        name="📈 Promoções",
                        value="Receba notificação sobre promoções de membros",
                        inline=False
                    )
                    embed.add_field(
                        name="⚠️ Rejeições",
                        value="Receba notificação quando promoções forem rejeitadas",
                        inline=False
                    )
                    embed.set_footer(text="Clique nos botões para ativar/desativar notificações")
                    
                    embed.add_field(
                        name="📍 Canal de Logs",
                        value=f"Este canal foi definido como canal de logs para o servidor.",
                        inline=False
                    )
                    embed.set_footer(text="Todos os eventos vão ser enviados aqui quando acontecerem.")

                    view = LogsView(server_id)
                    await channel.send(embed=embed, view=view)
            except Exception as e:
                print(f"Erro ao reenviar setup de logs para {guild.name}: {e}")

@bot.event
async def on_message(message):
    try:
        if message.author.bot:
            return

        if not message.guild:
            content = message.content.strip()
            if not content:
                return

            for guild in bot.guilds:
                member = guild.get_member(message.author.id)
                if not member:
                    continue

                config = db.get_config(str(guild.id))
                canal_id = config.get("canal_inatividade")
                if not canal_id:
                    continue

                channel = guild.get_channel(int(canal_id)) if canal_id else None
                if not channel:
                    continue

                embed = discord.Embed(
                    title="📨 Resposta de inatividade recebida",
                    description=content[:2000],
                    color=discord.Color.orange()
                )
                embed.add_field(name="Usuário", value=f"{message.author} ({message.author.id})", inline=False)
                embed.add_field(name="Servidor", value=guild.name, inline=False)
                embed.set_footer(text="Mensagem recebida via DM")

                try:
                    await channel.send(embed=embed)
                except Exception:
                    pass

            return

        content = message.content.lower()

        # Se for um canal de ticket e a mensagem vier do dono do ticket, avisar somente se for o formulário
        if message.channel and message.channel.name.startswith("ticket-"):
            try:
                ticket_owner_id = int(message.channel.name.replace("ticket-", ""))
            except ValueError:
                ticket_owner_id = None

            if ticket_owner_id and message.author.id == ticket_owner_id:
                markers = [
                    "nickname no roblox",
                    "usuário do discord",
                    "nacionalidade",
                    "jura lealdade",
                    "atividade é crucial",
                    "cargos selecionáveis",
                    "pretende focar",
                    "solicitou no grupo"
                ]
                found = sum(1 for marker in markers if marker in content)

                if found >= 3:
                    try:
                        await message.add_reaction("✅")
                        await message.add_reaction("❌")
                        await message.reply(
                            "✅ Formulário recebido! Aguarde um membro da equipe revisar sua solicitação.",
                            mention_author=False
                        )
                    except Exception:
                        pass

        # Comando +registro treino
        if content == "+registro treino":
            if not message.author.guild_permissions.manage_roles:
                await message.reply("❌ Você não tem permissão para registrar treinos.", mention_author=False)
                return

            server_id = str(message.guild.id)
            config = db.get_config(server_id)
            if config.get("sistema_ativo", 1) == 0:
                return

            canal_id = config.get("canal_treinos") or str(message.channel.id)
            channel = message.guild.get_channel(int(canal_id)) if canal_id else message.channel
            if not channel:
                channel = message.channel

            pontos_por_treino = config.get("pontos_por_treino", 2)
            cargo_ping = config.get("cargo_ping_treinos", "")
            treino_id = db.create_treino(server_id, str(message.author.id), "Treino", "", "", str(channel.id), pontos_por_treino, cargo_ping)
            treino = db.get_treino(treino_id)

            embed = discord.Embed(
                title="🏋️ Treino Registrado!",
                description="Um novo treino foi registrado. Confirme se você vai participar:",
                color=discord.Color.blue()
            )
            embed.set_footer(text="Use os botões abaixo para confirmar presença.")

            view = EventoConfirmView(treino_id, server_id)
            msg = await channel.send(embed=embed, view=view)
            db.update_treino_mensagem(treino_id, str(msg.id))

            if config.get("dm_treinos", 1) == 1:
                cargo_ping = config.get("cargo_ping_treinos")
                if cargo_ping:
                    role = message.guild.get_role(int(cargo_ping))
                    if role:
                        embed_dm = discord.Embed(
                            title="🏋️ Novo Treino!",
                            description=f"Um treino foi registrado em {message.guild.name}.",
                            color=discord.Color.blue()
                        )
                        embed_dm.add_field(name="Canal", value=channel.mention, inline=False)
                        embed_dm.set_footer(text="Confirme sua presença clicando nos botões na mensagem do canal.")

                        count = 0
                        for member in message.guild.members:
                            if role in member.roles:
                                try:
                                    await member.send(embed=embed_dm)
                                    count += 1
                                except Exception:
                                    pass
                        await message.reply(f"✅ Treino registrado! {count} membros notificados via DM.", mention_author=False)
                    else:
                        await message.reply("❌ Cargo de ping treinos não encontrado.", mention_author=False)
                else:
                    await message.reply("❌ Cargo de ping treinos não configurado.", mention_author=False)
            else:
                await message.reply("✅ Treino registrado!", mention_author=False)

            return

        server_id = str(message.guild.id)
        config = db.get_config(server_id)
        if config.get("sistema_ativo", 1) == 0:
            return

        user = db.create_or_update_user(server_id, str(message.author.id), str(message.author))
        db.update_last_activity(server_id, str(message.author.id))
        cooldown = config.get("cooldown_msg", 60)
        now = int(datetime.now().timestamp())
        if now - user.get("ultimo_xp_msg", 0) < cooldown:
            return

        xp = config.get("pontos_por_msg", 10)
        db.add_xp(server_id, str(message.author.id), xp, "mensagem")
        if config.get("log_xp", 0) == 1:
            log_embed = discord.Embed(
                title="⭐ XP Adicionado",
                description=f"{message.author.mention} ganhou {xp} XP por mensagem.",
                color=discord.Color.green()
            )
            await send_log(message.guild, "xp", embed=log_embed)
        await check_promotion(message.guild, message.author, config)

    except Exception as e:
        print("Erro no on_message:", e)

    try:
        await bot.process_commands(message)
    except Exception as e:
        print("Erro ao processar comandos:", e)

@bot.event
async def on_raw_reaction_add(payload):
    try:
        if payload.user_id == bot.user.id:
            return

        emoji = str(payload.emoji)
        if emoji not in ["✅", "❌"]:
            return

        if not payload.guild_id or not payload.channel_id:
            return

        guild = bot.get_guild(payload.guild_id)
        if not guild:
            return

        member = guild.get_member(payload.user_id)
        if not member or not member.guild_permissions.administrator:
            return

        channel = guild.get_channel(payload.channel_id)
        if not channel or not channel.name.startswith("ticket-"):
            return

        try:
            message = await channel.fetch_message(payload.message_id)
        except Exception:
            return

        if message.author.bot:
            return

        target_member = guild.get_member(message.author.id)
        if not target_member:
            return

        config = db.get_config(str(guild.id))
        cargo_id = config.get("cargo_verificado")
        role = guild.get_role(int(cargo_id)) if cargo_id else None

        if emoji == "✅":
            if not cargo_id or not role:
                await channel.send("❌ Cargo de verificado não configurado ou não encontrado. Use /set_verified_role para definir.")
                return
            if role not in target_member.roles:
                try:
                    await target_member.add_roles(role, reason="Verificado por staff")
                    await channel.send(f"✅ {target_member.mention} recebeu o cargo {role.mention}.")
                    try:
                        await target_member.send(
                            f"✅ Parabéns! Sua solicitação de verificação foi aprovada no servidor {guild.name}. "
                            f"Você recebeu o cargo {role.name}."
                        )
                    except Exception:
                        pass
                except Exception as e:
                    await channel.send(f"❌ Erro ao adicionar cargo: {str(e)}")
            else:
                await channel.send(f"✅ {target_member.mention} já possui o cargo {role.mention}.")
        else:
            try:
                await target_member.send(
                    "❌ Sua solicitação foi analisada pela equipe e não foi aprovada. "
                    "Por favor, revise as instruções e tente novamente se desejar."
                )
            except Exception:
                pass
            await channel.send(f"❌ Solicitação de {target_member.mention} foi recusada pelo staff.")
    except Exception as e:
        print("Erro em on_raw_reaction_add:", e)

def get_next_lower_role(role_key: str) -> Optional[str]:
    if role_key not in ROLE_SUFFIXES:
        return None
    index = ROLE_SUFFIXES.index(role_key)
    if index <= 0:
        return None
    return ROLE_SUFFIXES[index - 1]

async def ensure_role_for_key(guild: discord.Guild, config: dict, role_key: str) -> Optional[discord.Role]:
    role_id = config.get(f"cargo_{role_key}")
    if not role_id:
        return None
    return guild.get_role(int(role_id))

@tasks.loop(minutes=60)
async def inactivity_task():
    now_ts = int(datetime.now().timestamp())
    for guild in bot.guilds:
        server_id = str(guild.id)
        config = db.get_config(server_id)
        users = db.get_users_with_activity(server_id)

        for user_data in users:
            last_activity = user_data.get("ultimo_atividade", 0)
            if last_activity <= 0:
                continue

            member = guild.get_member(int(user_data["discord_id"]))
            if not member:
                continue

            if user_data.get("ultimo_inatividade_3d", 0) == 0:
                if now_ts - last_activity >= 3 * 24 * 60 * 60:
                    try:
                        await member.send(
                            "👋 Olá! Você está inativo há 3 dias. "
                            "Esta é uma mensagem automática, não é adm. "
                            "Por favor, responda esta mensagem ou volte a interagir no servidor para evitar ações automáticas."
                        )
                        db.mark_inactivity_warning(server_id, str(member.id), 3)
                    except Exception:
                        pass

            if user_data.get("ultimo_inatividade_7d", 0) == 0:
                if now_ts - last_activity >= 7 * 24 * 60 * 60:
                    try:
                        await member.send(
                            "⚠️ Você está inativo há 7 dias. "
                            "Precisamos de sua resposta para manter seu cargo. "
                            "Responda esta mensagem ou volte a participar no servidor."
                        )
                        db.mark_inactivity_warning(server_id, str(member.id), 7)
                    except Exception:
                        pass

            if user_data.get("rebaixado_inativo", 0) == 0:
                if now_ts - last_activity >= 10 * 24 * 60 * 60:
                    current_role = user_data.get("cargo_atual")
                    lower_role_key = get_next_lower_role(current_role or "")
                    if lower_role_key:
                        current_discord_role = await ensure_role_for_key(guild, config, current_role)
                        lower_discord_role = await ensure_role_for_key(guild, config, lower_role_key)
                        try:
                            if current_discord_role and current_discord_role in member.roles:
                                await member.remove_roles(current_discord_role, reason="Rebaixamento por inatividade")
                            if lower_discord_role:
                                await member.add_roles(lower_discord_role, reason="Rebaixamento por inatividade")
                                db.update_user_role(server_id, str(member.id), lower_role_key)
                                await member.send(
                                    "⏳ Você foi rebaixado por 10 dias de inatividade. "
                                    f"Seu novo cargo agora é {lower_discord_role.name}."
                                )
                            else:
                                await member.send(
                                    "⏳ Você foi considerado para rebaixamento por 10 dias de inatividade, "
                                    "mas não há cargo inferior configurado."
                                )
                            db.mark_inactivity_demoted(server_id, str(member.id))
                        except Exception:
                            pass
                    else:
                        db.mark_inactivity_demoted(server_id, str(member.id))

async def check_promotion(guild: discord.Guild, member: discord.Member, config: dict):
    server_id = str(guild.id)
    user = db.get_user(server_id, str(member.id))
    if not user:
        return None

    xp = user["xp"]
    auto_promover_global = config.get("auto_promover", 1) == 1
    usar_dm = config.get("usar_dm", 1) == 1

    patentes = db.get_patentes_ordenadas_por_xp(server_id)
    if not patentes:
        return None

    current_cargo = user.get("cargo_atual", "").lower()
    new_patente = None

    for patente in sorted(patentes, key=lambda x: x.get("xp_necessario", 0), reverse=True):
        if xp >= patente["xp_necessario"] and current_cargo != patente["nome"].lower():
            new_patente = patente
            break

    if not new_patente:
        return None

    if new_patente.get("auto_promover", 1) == 0 or not auto_promover_global:
        return None

    role_id = new_patente.get("role_id")
    if not role_id:
        return None

    role = guild.get_role(int(role_id))
    if not role:
        return None

    try:
        await member.add_roles(role)
        db.update_user_role(server_id, str(member.id), new_patente["nome"].lower())
        db.add_xp(server_id, str(member.id), 0, "promocao", f"Auto-promovido para {new_patente['nome']}")

        if usar_dm:
            try:
                await member.send(f"🎉 Parabéns! Você foi promovido para {role.name} no servidor {guild.name}!")
            except:
                pass

        return {
            "type": "auto",
            "role_name": role.name,
            "patente": new_patente["nome"]
        }
    except Exception as e:
        print(f"Erro ao promover {member}: {e}")
        return None

@bot.tree.command(name="xp", description="Mostra seu XP atual")
async def xp(interaction: discord.Interaction):
    server_id = str(interaction.guild.id)
    user = db.get_user(server_id, str(interaction.user.id))
    if user:
        await interaction.response.send_message(f"⭐ Seu XP: {user['xp']}")
    else:
        await interaction.response.send_message("❌ Dados não encontrados.")

@bot.tree.command(name="ranking", description="Exibe o ranking de XP")
@app_commands.describe(limit="Número de usuários a mostrar (padrão: 10)")
async def ranking(interaction: discord.Interaction, limit: int = 10):
    server_id = str(interaction.guild.id)
    ranking = db.get_ranking(server_id, limit)
    if not ranking:
        await interaction.response.send_message("📊 Nenhum usuário encontrado.")
        return

    embed = discord.Embed(title="🏆 Ranking de XP", color=discord.Color.gold())
    for i, user in enumerate(ranking, 1):
        embed.add_field(
            name=f"{i}. {user['username']}",
            value=f"⭐ {user['xp']} XP",
            inline=False
        )

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="addxp", description="Adiciona XP a um usuário (staff)")
@app_commands.describe(user="Usuário", amount="Quantidade de XP", reason="Motivo")
async def addxp(interaction: discord.Interaction, user: discord.Member, amount: int, reason: str = "Manual"):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return

    if amount <= 0:
        await interaction.response.send_message("❌ Quantidade deve ser positiva.", ephemeral=True)
        return

    server_id = str(interaction.guild.id)
    db.add_xp(server_id, str(user.id), amount, "manual", reason)
    await interaction.response.send_message(f"✅ Adicionado {amount} XP para {user.mention}. Motivo: {reason}")

@bot.tree.command(name="help", description="Mostra ajuda")
async def help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 Ajuda do Bot",
        description="Sistema completo de gerenciamento Discord com XP, patentes, eventos e tickets.",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="📌 Configuração",
        value="`/setup_logs` - Logs gerais (promoções, configs)\n"
              "`/setup_logs_evento` - Logs de eventos/treinos\n"
              "`/setup_logs_ticket` - Logs de tickets\n"
              "`/setup_dm` - Configurar notificações DM\n"
              "`/setup_xp` - Configurar XP por mensagem, registro e cooldown\n"
              "`/setup_patentes` - Gerenciar patentes do servidor\n"
              "`/set_verified_role` - Cargo verificado para tickets\n"
              "`/set_canal_evento` - Define o canal de eventos",
        inline=False
    )
    
    embed.add_field(
        name="⭐ XP e Patentes",
        value="`/xp` - Ver seu XP atual\n"
              "`/ranking` - Ranking de XP\n"
              "`/addxp` - Adicionar XP (staff)\n"
              "`/promote` - Promover manualmente (staff)\n"
              "`/demote` - Rebaixar (staff)\n"
              "`/clear-xp` - Limpar XP (staff)\n"
              "`/hierarchy` - Ver hierarquia de patentes",
        inline=False
    )
    
    embed.add_field(
        name="🏆 Eventos",
        value="`/novo_evento` - Criar evento via modal\n"
              "`/resultadoevento` - Registrar resultado e distribuir XP",
        inline=False
    )
    
    embed.add_field(
        name="🎫 Tickets",
        value="`/setup_ticket` - Configurar sistema de tickets\n"
              "`/close` - Fechar ticket atual",
        inline=False
    )
    
    embed.add_field(
        name="📊 Atividade",
        value="`/last_active` - Quando usuário falou por último\n"
              "`/activity_status` - Atividade em chat + eventos\n"
              "`/user` - Perfil/XP de usuário",
        inline=False
    )
    
    embed.set_footer(text="Use /comando para mais detalhes sobre cada função")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="hierarchy", description="Mostra hierarquia de patentes do servidor")
async def hierarchy(interaction: discord.Interaction):
    server_id = str(interaction.guild.id)
    patentes = db.get_patentes_ordenadas_por_xp(server_id)
    
    if not patentes:
        await interaction.response.send_message("📊 Nenhuma patente configurada neste servidor.", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="📊 Hierarquia do Servidor",
        description="Patentes organizadas por XP necessário",
        color=discord.Color.gold()
    )
    
    for patente in patentes:
        role_mention = f"<@&{patente['role_id']}>" if patente['role_id'] else "Cargo não configurado"
        promocao_text = "Automática" if patente.get("auto_promover", 1) == 1 else "Manual"
        embed.add_field(
            name=f"{patente['nome']}",
            value=f"⭐ {patente['xp_necessario']} XP — {role_mention} — {promocao_text}",
            inline=False
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="user", description="Ver perfil/XP de um usuário")
@app_commands.describe(user="Usuário")
async def user(interaction: discord.Interaction, user: discord.Member):
    server_id = str(interaction.guild.id)
    user_data = db.get_user(server_id, str(user.id))
    
    if not user_data:
        await interaction.response.send_message("❌ Usuário não encontrado no banco de dados.", ephemeral=True)
        return
    
    embed = discord.Embed(
        title=f"👤 Perfil de {user.name}",
        color=discord.Color.blue()
    )
    embed.add_field(name="Discord ID", value=user.id, inline=False)
    embed.add_field(name="⭐ XP Total", value=user_data.get("xp", 0), inline=False)
    embed.add_field(name="🎖️ Cargo Atual", value=user_data.get("cargo_atual", "Recruta"), inline=False)
    embed.set_thumbnail(url=user.display_avatar.url)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="promote", description="Promover usuário manualmente (staff)")
@app_commands.describe(user="Usuário a promover", role="Novo cargo")
async def promote(interaction: discord.Interaction, user: discord.Member, role: str):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return
    
    server_id = str(interaction.guild.id)
    
    # Get patente by name
    patentes = db.get_patentes(server_id)
    patente = next((p for p in patentes if p["nome"].lower() == role.lower()), None)
    if not patente or not patente.get("role_id"):
        await interaction.response.send_message(f"❌ Cargo '{role}' não configurado no servidor.", ephemeral=True)
        return
    
    role_id = patente["role_id"]
    discord_role = interaction.guild.get_role(int(role_id))
    if not discord_role:
        await interaction.response.send_message("❌ Cargo não encontrado no Discord.", ephemeral=True)
        return
    
    try:
        await user.add_roles(discord_role)
        db.update_user_role(server_id, str(user.id), role.lower())
        db.add_xp(server_id, str(user.id), 0, "promocao_manual", f"Promovido para {role} por {interaction.user.name}")
        
        await interaction.response.send_message(f"✅ {user.mention} promovido para {discord_role.mention}!")
    except Exception as e:
        await interaction.response.send_message(f"❌ Erro ao promover: {str(e)}", ephemeral=True)

@bot.tree.command(name="demote", description="Rebaixar usuário (staff)")
@app_commands.describe(user="Usuário a rebaixar", role="Cargo a remover")
async def demote(interaction: discord.Interaction, user: discord.Member, role: str):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return
    
    server_id = str(interaction.guild.id)
    
    # Get patente by name
    patentes = db.get_patentes(server_id)
    patente = next((p for p in patentes if p["nome"].lower() == role.lower()), None)
    if not patente or not patente.get("role_id"):
        await interaction.response.send_message(f"❌ Cargo '{role}' não configurado.", ephemeral=True)
        return
    
    role_id = patente["role_id"]
    discord_role = interaction.guild.get_role(int(role_id))
    if not discord_role:
        await interaction.response.send_message("❌ Cargo não encontrado.", ephemeral=True)
        return
    
    try:
        await user.remove_roles(discord_role)
        db.update_user_role(server_id, str(user.id), "recruta")
        db.add_xp(server_id, str(user.id), 0, "rebaixamento", f"Rebaixado de {role} por {interaction.user.name}")
        
        await interaction.response.send_message(f"✅ {user.mention} rebaixado!")
    except Exception as e:
        await interaction.response.send_message(f"❌ Erro ao rebaixar: {str(e)}", ephemeral=True)

@bot.tree.command(name="clear-xp", description="Limpar XP de um usuário (staff)")
@app_commands.describe(user="Usuário", reason="Motivo da limpeza")
async def clear_xp(interaction: discord.Interaction, user: discord.Member, reason: str = "Sem motivo"):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return
    
    server_id = str(interaction.guild.id)
    
    try:
        # Limpar XP (resetar para 0)
        db.add_xp(server_id, str(user.id), -9999999, "reset_xp", f"XP resetado por {interaction.user.name}. Motivo: {reason}")
        
        await interaction.response.send_message(f"✅ XP de {user.mention} foi zerado. Motivo: {reason}")
    except Exception as e:
        await interaction.response.send_message(f"❌ Erro ao limpar XP: {str(e)}", ephemeral=True)

@bot.tree.command(name="setup_ticket", description="Configura o sistema de tickets neste canal (staff)")
async def setup_ticket(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return

    embed = discord.Embed(
        title="� Identificação",
        description=(
            "Para dar início ao processo de emissão do passaporte, abra um ticket e aguarde o contato de um membro da staff, "
            "que fornecerá o formulário oficial."
        ),
        color=discord.Color.blue()
    )
    embed.add_field(
        name="Como funciona",
        value=(
            "1. Clique em 'Abrir Ticket' para criar um canal privado.\n"
            "2. Responda ao formulário de verificação com informações verdadeiras.\n"
            "3. A equipe irá revisar sua solicitação. Staff usará reações para aprovar ou rejeitar."
        ),
        inline=False
    )
    embed.add_field(
        name="Avaliação",
        value=(
            "✅ Aprovar — o usuário receberá o cargo configurado de verificado.\n"
            "❌ Rejeitar — o usuário não receberá o cargo e será informado da recusa."
        ),
        inline=False
    )
    embed.set_footer(text="Apenas staff autorizado pode abrir, analisar e responder tickets.")

    view = TicketView()
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="setup_logs", description="Configura logs gerais (staff)")
async def setup_logs(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return

    server_id = str(interaction.guild.id)
    db.set_log_channel(server_id, "gerais", str(interaction.channel.id))
    config = db.get_config(server_id)

    embed = discord.Embed(
        title="📝 Sistema de Logs Gerais",
        description="Logs gerais configurados neste canal.",
        color=discord.Color.blue()
    )
    embed.add_field(name="Canal", value=interaction.channel.mention, inline=True)
    embed.add_field(name="Logs gerais", value="✅ Ligado" if config.get("logs_gerais_enabled", 1) else "❌ Desligado", inline=True)
    embed.add_field(name="Logs XP", value="✅ Ligado" if config.get("logs_xp_enabled", 1) else "❌ Desligado", inline=True)
    embed.add_field(name="Logs Staff", value="✅ Ligado" if config.get("logs_staff_enabled", 1) else "❌ Desligado", inline=True)
    embed.set_footer(text="Logs de promoções, configurações e ações administrativas")

    view = LogsGeralView(str(interaction.guild.id))
    await interaction.response.send_message(embed=embed, view=view)

    # Log da configuração
    log_embed = discord.Embed(
        title="📌 Canal de Logs Gerais Configurado",
        description=f"Este canal foi definido como canal de logs gerais por {interaction.user.mention}.",
        color=discord.Color.blue()
    )
    await send_log(interaction.guild, "geral", embed=log_embed)

@bot.tree.command(name="setup_logs_evento", description="Configura logs de eventos (staff)")
async def setup_logs_evento(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return

    server_id = str(interaction.guild.id)
    db.set_log_channel(server_id, "eventos", str(interaction.channel.id))
    config = db.get_config(server_id)

    embed = discord.Embed(
        title="🏆 Sistema de Logs de Eventos",
        description="Logs de eventos configurados neste canal.",
        color=discord.Color.red()
    )
    embed.add_field(name="Canal", value=interaction.channel.mention, inline=True)
    embed.add_field(name="Logs de eventos", value="✅ Ligado" if config.get("logs_eventos_enabled", 1) else "❌ Desligado", inline=True)
    embed.add_field(name="Logs de respostas", value="✅ Ligado" if config.get("logs_eventos_respostas_enabled", 1) else "❌ Desligado", inline=True)
    embed.set_footer(text="Logs de criação, edição, cancelamento e resultados de eventos")

    view = LogsEventoView(str(interaction.guild.id))
    await interaction.response.send_message(embed=embed, view=view)

    # Log da configuração
    log_embed = discord.Embed(
        title="📌 Canal de Logs de Eventos Configurado",
        description=f"Este canal foi definido como canal de logs de eventos por {interaction.user.mention}.",
        color=discord.Color.red()
    )
    await send_log(interaction.guild, "evento", embed=log_embed)

def build_patentes_embed(guild: discord.Guild) -> discord.Embed:
    server_id = str(guild.id)
    patentes = db.get_patentes(server_id)
    embed = discord.Embed(
        title="⚔️ Patentes do Servidor",
        description="Lista de patentes atuais e seus cargos.",
        color=BOT_COLOR
    )

    if not patentes:
        embed.add_field(name="Patentes", value="Nenhuma patente configurada.", inline=False)
        return embed

    descricao = []
    for patente in patentes:
        role_text = f"<@&{patente['role_id']}>" if patente.get('role_id') else "Cargo não configurado"
        promocao = "Automática" if patente.get('auto_promover', 1) == 1 else "Manual"
        descricao.append(
            f"ID {patente['id']} — {patente['nome']}\n"
            f"Cargo: {role_text}\n"
            f"XP necessário: {patente['xp_necessario']}\n"
            f"Promoção: {promocao}"
        )

    embed.add_field(name="Patentes", value="\n\n".join(descricao), inline=False)
    return embed

class SetupPatentesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="➕ Adicionar patente", style=discord.ButtonStyle.success)
    async def add_patente(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddPatenteModal(interaction))

    @discord.ui.button(label="✏️ Editar patente", style=discord.ButtonStyle.primary)
    async def edit_patente(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditPatenteModal(interaction))

    @discord.ui.button(label="🗑️ Remover patente", style=discord.ButtonStyle.danger)
    async def remove_patente(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RemovePatenteModal(interaction))

    @discord.ui.button(label="🔄 Atualizar lista", style=discord.ButtonStyle.secondary)
    async def refresh_list(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = build_patentes_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)

class AddPatenteModal(discord.ui.Modal, title="Adicionar Patente"):
    nome = discord.ui.TextInput(label="Nome", style=discord.TextStyle.short, required=True, max_length=100)
    cargo = discord.ui.TextInput(label="Cargo (mention/ID/nome)", style=discord.TextStyle.short, required=False, max_length=100)
    xp = discord.ui.TextInput(label="XP necessário", style=discord.TextStyle.short, required=True, default="0")
    promocao = discord.ui.TextInput(label="Promoção (auto/manual)", style=discord.TextStyle.short, required=True, default="auto")
    ordem = discord.ui.TextInput(label="Ordem", style=discord.TextStyle.short, required=True, default="0")

    def __init__(self, interaction: discord.Interaction):
        super().__init__()
        self.interaction = interaction

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
            return

        server_id = str(interaction.guild.id)
        role = None
        if self.cargo.value:
            role = parse_role_from_input(interaction.guild, self.cargo.value)

        if role:
            role_id = str(role.id)
        else:
            role_result = DiscordAPI.ensure_discord_role(server_id, self.cargo.value.strip() if self.cargo.value else self.nome.value.strip())
            if "error" in role_result:
                await interaction.response.send_message(f"❌ Não foi possível criar ou encontrar o cargo: {role_result.get('message')}", ephemeral=True)
                return
            role_id = str(role_result.get("id"))

        try:
            xp_value = int(self.xp.value.strip())
            ordem_value = int(self.ordem.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ XP e ordem devem ser números inteiros.", ephemeral=True)
            return

        auto_promover = 1 if self.promocao.value.strip().lower() == "auto" else 0
        db.create_patente(server_id, self.nome.value.strip(), role_id, xp_value, ordem_value, 1, auto_promover)
        await interaction.response.send_message("✅ Patente adicionada com sucesso.", ephemeral=True)

class EditPatenteModal(discord.ui.Modal, title="Editar Patente"):
    patente_id = discord.ui.TextInput(label="ID da patente", style=discord.TextStyle.short, required=True)
    nome = discord.ui.TextInput(label="Nome (opcional)", style=discord.TextStyle.short, required=False, max_length=100)
    cargo = discord.ui.TextInput(label="Cargo (opcional)", style=discord.TextStyle.short, required=False, max_length=100)
    xp = discord.ui.TextInput(label="XP necessário (opcional)", style=discord.TextStyle.short, required=False, default="")
    promocao = discord.ui.TextInput(label="Promoção (auto/manual) (opcional)", style=discord.TextStyle.short, required=False, default="")

    def __init__(self, interaction: discord.Interaction):
        super().__init__()
        self.interaction = interaction

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
            return

        server_id = str(interaction.guild.id)
        if not self.patente_id.value.strip().isdigit():
            await interaction.response.send_message("❌ ID inválido.", ephemeral=True)
            return

        patente_id = int(self.patente_id.value.strip())
        patente = db.get_patente_by_id(server_id, patente_id)
        if not patente:
            await interaction.response.send_message("❌ Patente não encontrada.", ephemeral=True)
            return

        data = {}
        if self.nome.value.strip():
            data["nome"] = self.nome.value.strip()
        if self.cargo.value.strip():
            role = parse_role_from_input(interaction.guild, self.cargo.value)
            if role:
                data["role_id"] = str(role.id)
            else:
                role_result = DiscordAPI.ensure_discord_role(server_id, self.cargo.value.strip())
                if "error" in role_result:
                    await interaction.response.send_message(f"❌ Não foi possível criar ou encontrar o cargo: {role_result.get('message')}", ephemeral=True)
                    return
                data["role_id"] = str(role_result.get("id"))
        if self.xp.value.strip():
            try:
                data["xp_necessario"] = int(self.xp.value.strip())
            except ValueError:
                await interaction.response.send_message("❌ XP precisa ser um número inteiro.", ephemeral=True)
                return
        if self.promocao.value.strip():
            data["auto_promover"] = 1 if self.promocao.value.strip().lower() == "auto" else 0

        if not data:
            await interaction.response.send_message("❌ Nenhum campo para atualizar.", ephemeral=True)
            return

        success = db.update_patente(patente_id, server_id, data)
        if not success:
            await interaction.response.send_message("❌ Falha ao atualizar a patente.", ephemeral=True)
            return

        await interaction.response.send_message("✅ Patente atualizada com sucesso.", ephemeral=True)

class RemovePatenteModal(discord.ui.Modal, title="Remover Patente"):
    patente_id = discord.ui.TextInput(label="ID da patente", style=discord.TextStyle.short, required=True)

    def __init__(self, interaction: discord.Interaction):
        super().__init__()
        self.interaction = interaction

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
            return

        server_id = str(interaction.guild.id)
        if not self.patente_id.value.strip().isdigit():
            await interaction.response.send_message("❌ ID inválido.", ephemeral=True)
            return

        patente_id = int(self.patente_id.value.strip())
        result = db.delete_patente(patente_id, server_id)
        if result is None:
            await interaction.response.send_message("❌ Patente não encontrada.", ephemeral=True)
            return
        if not result:
            await interaction.response.send_message("❌ Esta patente não pode ser removida.", ephemeral=True)
            return

        await interaction.response.send_message("✅ Patente removida com sucesso.", ephemeral=True)

@bot.tree.command(name="setup_patentes", description="Configura as patentes do servidor (staff)")
async def setup_patentes(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return

    embed = build_patentes_embed(interaction.guild)
    view = SetupPatentesView()
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="setup_logs_ticket", description="Configura logs de tickets (staff)")
async def setup_logs_ticket(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return

    server_id = str(interaction.guild.id)
    db.set_log_channel(server_id, "tickets", str(interaction.channel.id))
    config = db.get_config(server_id)

    embed = discord.Embed(
        title="🎫 Sistema de Logs de Tickets",
        description="Logs de tickets configurados neste canal.",
        color=discord.Color.purple()
    )
    embed.add_field(name="Canal", value=interaction.channel.mention, inline=True)
    embed.add_field(name="Logs de tickets", value="✅ Ligado" if config.get("logs_tickets_enabled", 1) else "❌ Desligado", inline=True)
    embed.set_footer(text="Logs de abertura e fechamento de tickets")

    view = LogsTicketView(str(interaction.guild.id))
    await interaction.response.send_message(embed=embed, view=view)

    # Log da configuração
    log_embed = discord.Embed(
        title="📌 Canal de Logs de Tickets Configurado",
        description=f"Este canal foi definido como canal de logs de tickets por {interaction.user.mention}.",
        color=discord.Color.purple()
    )
    await send_log(interaction.guild, "geral", embed=log_embed)

@bot.tree.command(name="setup_dm", description="Configura notificações por DM (staff)")
async def setup_dm(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return

    server_id = str(interaction.guild.id)
    dm_config = db.get_dm_config(server_id)

    embed = discord.Embed(
        title="� Notificações por DM",
        description="Configure quais notificações serão enviadas por DM.",
        color=discord.Color.green()
    )
    embed.add_field(name="DM Promoções", value="✅ Ligado" if dm_config["promocoes"] else "❌ Desligado", inline=True)
    embed.add_field(name="DM Eventos", value="✅ Ligado" if dm_config["eventos"] else "❌ Desligado", inline=True)
    embed.add_field(name="DM Tickets", value="✅ Ligado" if dm_config["tickets"] else "❌ Desligado", inline=True)
    embed.add_field(name="DM Staff", value="✅ Ligado" if dm_config["staff"] else "❌ Desligado", inline=True)
    embed.set_footer(text="Clique nos botões para alternar configurações")

    view = DMNotificationsView(str(interaction.guild.id))
    await interaction.response.send_message(embed=embed, view=view)

class SetupXPModal(discord.ui.Modal, title="Editar Configuração de XP"):
    xp_mensagem = discord.ui.TextInput(label="XP por mensagem", style=discord.TextStyle.short, required=False, placeholder="Ex: 10")
    xp_registro = discord.ui.TextInput(label="XP por registro", style=discord.TextStyle.short, required=False, placeholder="Ex: 50")
    cooldown = discord.ui.TextInput(label="Cooldown em segundos", style=discord.TextStyle.short, required=False, placeholder="Ex: 60")

    def __init__(self, interaction: discord.Interaction):
        super().__init__()
        self.interaction = interaction

    async def on_submit(self, interaction: discord.Interaction):
        server_id = str(interaction.guild.id)
        updates = {}
        errors = []

        if self.xp_mensagem.value.strip():
            try:
                val = int(self.xp_mensagem.value.strip())
                if val < 0:
                    raise ValueError
                updates["pontos_por_msg"] = val
            except ValueError:
                errors.append("XP por mensagem deve ser um número inteiro >= 0")

        if self.xp_registro.value.strip():
            try:
                val = int(self.xp_registro.value.strip())
                if val < 0:
                    raise ValueError
                updates["pontos_por_registro"] = val
            except ValueError:
                errors.append("XP por registro deve ser um número inteiro >= 0")

        if self.cooldown.value.strip():
            try:
                val = int(self.cooldown.value.strip())
                if val < 0:
                    raise ValueError
                updates["cooldown_msg"] = val
            except ValueError:
                errors.append("Cooldown deve ser um número inteiro >= 0")

        if errors:
            await interaction.response.send_message("❌ " + "\n".join(errors), ephemeral=True)
            return

        if not updates:
            await interaction.response.send_message("❌ Você precisa preencher pelo menos um campo.", ephemeral=True)
            return

        db.set_xp_config(server_id, **updates)
        await interaction.response.send_message("✅ Configuração de XP atualizada.", ephemeral=True)

class SetupXPView(discord.ui.View):
    def __init__(self, server_id: str):
        super().__init__(timeout=None)
        self.server_id = server_id

    async def refresh_embed(self, interaction: discord.Interaction):
        config = db.get_config(self.server_id)
        embed = discord.Embed(
            title="⭐ Configuração de XP",
            description="Configure o sistema de XP do servidor.",
            color=discord.Color.red()
        )
        embed.add_field(name="XP por mensagem", value=str(config.get("pontos_por_msg", 10)), inline=True)
        embed.add_field(name="XP por registro", value=str(config.get("pontos_por_registro", 50)), inline=True)
        embed.add_field(name="Cooldown por mensagem", value=f"{config.get('cooldown_msg', 60)} segundos", inline=True)
        embed.add_field(name="Sistema ativo", value="✅ Ligado" if config.get("sistema_ativo", 1) else "❌ Desligado", inline=True)
        embed.set_footer(text="Clique nos botões para alterar configurações")
        await interaction.message.edit(embed=embed, view=SetupXPView(self.server_id))

    @discord.ui.button(label="Editar XP", style=discord.ButtonStyle.primary)
    async def edit_xp(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
            return
        await interaction.response.send_modal(SetupXPModal(interaction))

    @discord.ui.button(label="Ativar sistema", style=discord.ButtonStyle.success)
    async def enable_system(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        db.set_xp_config(self.server_id, sistema_ativo=1)
        await self.refresh_embed(interaction)
        await interaction.followup.send("Sistema de XP ativado.", ephemeral=True)

    @discord.ui.button(label="Desativar sistema", style=discord.ButtonStyle.danger)
    async def disable_system(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        db.set_xp_config(self.server_id, sistema_ativo=0)
        await self.refresh_embed(interaction)
        await interaction.followup.send("Sistema de XP desativado.", ephemeral=True)

    @discord.ui.button(label="Atualizar", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self.refresh_embed(interaction)
        await interaction.followup.send("Embed atualizado.", ephemeral=True)

@bot.tree.command(name="setup_xp", description="Configura XP por mensagem, XP por registro e cooldown (staff)")
async def setup_xp(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return

    server_id = str(interaction.guild.id)
    config = db.get_config(server_id)

    embed = discord.Embed(
        title="⭐ Configuração de XP",
        description="Configure o sistema de XP do servidor.",
        color=discord.Color.red()
    )
    embed.add_field(name="XP por mensagem", value=str(config.get("pontos_por_msg", 10)), inline=True)
    embed.add_field(name="XP por registro", value=str(config.get("pontos_por_registro", 50)), inline=True)
    embed.add_field(name="Cooldown por mensagem", value=f"{config.get('cooldown_msg', 60)} segundos", inline=True)
    embed.add_field(name="Sistema ativo", value="✅ Ligado" if config.get("sistema_ativo", 1) else "❌ Desligado", inline=True)
    embed.set_footer(text="Clique nos botões para alterar configurações")

    view = SetupXPView(server_id)
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="close", description="Fecha o ticket atual (staff)")
async def close(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return

    if not interaction.channel or not interaction.channel.name.startswith("ticket-"):
        await interaction.response.send_message("❌ Este comando só pode ser usado em canais de ticket.", ephemeral=True)
        return

    await interaction.response.send_message("🔒 Ticket fechado!", ephemeral=True)
    await asyncio.sleep(3)
    await interaction.channel.delete()

@bot.tree.command(name="set_ping_treinos", description="Define o cargo para ping de treinos (staff)")
@app_commands.describe(role="Cargo para ping de treinos")
async def set_ping_treinos(interaction: discord.Interaction, role: discord.Role):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return

    server_id = str(interaction.guild.id)
    config = db.get_config(server_id)
    config["cargo_ping_treinos"] = str(role.id)
    db.save_config(config)

    await interaction.response.send_message(f"✅ Cargo de ping treinos definido como {role.mention}!")

@bot.tree.command(name="set_verified_role", description="Define o cargo de verificado para tickets")
@app_commands.describe(role="Cargo que será dado quando staff marcar o formulário")
async def set_verified_role(interaction: discord.Interaction, role: discord.Role):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return

    server_id = str(interaction.guild.id)
    config = db.get_config(server_id)
    config["cargo_verificado"] = str(role.id)
    db.save_config(config)

    await interaction.response.send_message(f"✅ Cargo de verificado definido como {role.mention}!", ephemeral=True)

@bot.tree.command(name="set_canal_treino", description="Define o canal para treinos (staff)")
@app_commands.describe(channel="Canal para treinos")
async def set_canal_treino(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return

    server_id = str(interaction.guild.id)
    config = db.get_config(server_id)
    config["canal_treinos"] = str(channel.id)
    db.save_config(config)

    await interaction.response.send_message(f"✅ Canal de treinos definido como {channel.mention}!", ephemeral=True)

@bot.tree.command(name="set_canal_evento", description="Define o canal para eventos (staff)")
@app_commands.describe(channel="Canal para eventos")
async def set_canal_evento(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return

    server_id = str(interaction.guild.id)
    config = db.get_config(server_id)
    config["canal_eventos"] = str(channel.id)
    db.save_config(config)

    await interaction.response.send_message(f"✅ Canal de eventos definido como {channel.mention}!", ephemeral=True)

class NovoEventoModal(discord.ui.Modal, title="Novo Evento"):
    titulo = discord.ui.TextInput(label="Título do evento", style=discord.TextStyle.short, required=True, max_length=100)
    descricao = discord.ui.TextInput(label="Descrição do evento", style=discord.TextStyle.paragraph, required=True, max_length=1024)
    data_hora = discord.ui.TextInput(label="Data e hora (opcional)", style=discord.TextStyle.short, required=False, placeholder="DD/MM/YYYY HH:MM ou deixe em branco")
    pontos = discord.ui.TextInput(label="XP por confirmação", style=discord.TextStyle.short, required=True, default="2")
    alvos = discord.ui.TextInput(label="Alvos (cargos e usuários)", style=discord.TextStyle.paragraph, required=False, placeholder="@cargo1 @user1, nomes ou IDs separados por vírgula")

    def __init__(self, interaction: discord.Interaction):
        super().__init__()
        self.interaction = interaction

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
            return

        server_id = str(interaction.guild.id)
        config = db.get_config(server_id)

        try:
            xp_amount = int(self.pontos.value.strip())
            if xp_amount < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ O valor de XP precisa ser um número inteiro zero ou positivo.", ephemeral=True)
            return

        publish_channel = None
        canal_eventos = config.get("canal_eventos")
        if canal_eventos:
            publish_channel = interaction.guild.get_channel(int(canal_eventos))
        if not publish_channel:
            publish_channel = interaction.channel

        # Parse alvos (roles e users)
        target_roles = []
        target_users = []
        if self.alvos.value:
            alvo_parts = [part.strip() for part in self.alvos.value.split(',')]
            for part in alvo_parts:
                role = parse_role_from_input(interaction.guild, part)
                if role:
                    target_roles.append(role)
                    continue
                user_ids = parse_user_ids_from_text(part)
                target_users.extend(user_ids)
        if not target_roles and config.get("cargo_ping_treinos"):
            try:
                default_role = interaction.guild.get_role(int(config.get("cargo_ping_treinos")))
                if default_role:
                    target_roles.append(default_role)
            except Exception:
                pass

        # Parse data/hora
        horario_inicio = ""
        if self.data_hora.value:
            try:
                # Tentar parse DD/MM/YYYY HH:MM
                dt = datetime.strptime(self.data_hora.value.strip(), "%d/%m/%Y %H:%M")
                horario_inicio = dt.strftime("%d/%m/%Y %H:%M")
            except ValueError:
                try:
                    # Tentar parse DD/MM HH:MM (ano atual)
                    dt = datetime.strptime(f"{datetime.now().year}/{self.data_hora.value.strip()}", "%Y/%d/%m %H:%M")
                    horario_inicio = dt.strftime("%d/%m/%Y %H:%M")
                except ValueError:
                    await interaction.response.send_message("❌ Formato de data/hora inválido. Use DD/MM/YYYY HH:MM ou DD/MM HH:MM.", ephemeral=True)
                    return

        target_roles_str = ','.join(str(r.id) for r in target_roles)
        target_users_str = ','.join(target_users)
        treino_id = db.create_treino(
            server_id,
            str(interaction.user.id),
            self.titulo.value,
            self.descricao.value,
            horario_inicio,
            str(publish_channel.id),
            xp_amount,
            target_roles_str,
            target_users_str
        )

        embed = discord.Embed(
            title="Novo Evento Registrado",
            description=self.descricao.value,
            color=discord.Color.blue()
        )
        embed.add_field(name="Título", value=self.titulo.value, inline=False)
        embed.add_field(name="ID do Evento", value=str(treino_id), inline=True)
        embed.add_field(name="XP por confirmação", value=str(xp_amount), inline=True)
        embed.add_field(name="Canal", value=publish_channel.mention, inline=True)
        
        # Alvos
        alvo_text = ""
        if target_roles:
            alvo_text += "Cargos: " + " ".join(r.mention for r in target_roles)
        if target_users:
            user_mentions = []
            for uid in target_users:
                if uid.isdigit():
                    user_mentions.append(f"<@{uid}>")
            if user_mentions:
                if alvo_text:
                    alvo_text += "\n"
                alvo_text += "Usuários: " + " ".join(user_mentions)
        if not alvo_text:
            alvo_text = "Todos"
        embed.add_field(name="Alvo", value=alvo_text, inline=False)
        
        if horario_inicio:
            embed.add_field(name="Data/Hora", value=horario_inicio, inline=True)
        
        embed.add_field(name="Confirmados", value="0", inline=True)
        embed.add_field(name="Talvez", value="0", inline=True)
        embed.add_field(name="Não vou", value="0", inline=True)
        embed.set_footer(text=f"Criado por {interaction.user.display_name}")

        # Criar menção para ping
        ping_content = ""
        if target_roles:
            ping_content += " ".join(r.mention for r in target_roles)
        if target_users:
            if ping_content:
                ping_content += " "
            ping_content += " ".join(f"<@{uid}>" for uid in target_users if uid.isdigit())
        
        view = EventoConfirmView(treino_id, server_id)
        message_obj = await publish_channel.send(content=ping_content if ping_content else None, embed=embed, view=view, allowed_mentions=discord.AllowedMentions(roles=True, users=True))
        db.update_treino_mensagem(treino_id, str(message_obj.id))

        await interaction.response.send_message(f"✅ Evento criado em {publish_channel.mention}.", ephemeral=True)

@bot.tree.command(name="novo_evento", description="Cria um novo evento com título, XP e alvo (staff)")
async def novo_evento(interaction: discord.Interaction):
    await interaction.response.send_modal(NovoEventoModal(interaction))

class ResultadoEventoModal(discord.ui.Modal, title="Resultado do Evento"):
    treino_id = discord.ui.TextInput(label="ID do treino", style=discord.TextStyle.short, required=True)
    resultado = discord.ui.TextInput(label="Resumo do resultado", style=discord.TextStyle.paragraph, required=True)
    participantes = discord.ui.TextInput(label="Participantes confirmados", style=discord.TextStyle.paragraph, required=True, placeholder="Marque os participantes: @usuario1 @usuario2")
    xp = discord.ui.TextInput(label="XP por participante", style=discord.TextStyle.short, required=True, default="2")

    def __init__(self, interaction: discord.Interaction):
        super().__init__()
        self.interaction = interaction

    async def on_submit(self, interaction: discord.Interaction):
        server_id = str(interaction.guild.id)
        treino_id_value = self.treino_id.value.strip()
        if not treino_id_value.isdigit():
            await interaction.response.send_message("❌ ID do evento inválido.", ephemeral=True)
            return

        treino_id = int(treino_id_value)
        treino = db.get_treino(treino_id)
        if not treino or treino["server_id"] != server_id:
            await interaction.response.send_message("❌ Evento não encontrado neste servidor.", ephemeral=True)
            return

        try:
            xp_amount = int(self.xp.value.strip())
            if xp_amount < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ O valor de XP precisa ser um número inteiro zero ou positivo.", ephemeral=True)
            return

        respostas = db.get_treino_respostas(treino_id)
        confirmed_members = parse_confirmed_members(interaction.guild, self.participantes.value)
        if not confirmed_members:
            if self.participantes.value.strip():
                await interaction.response.send_message("❌ Nenhum participante foi encontrado. Use menção @usuario, ID ou nome exato.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Você precisa informar pelo menos um participante confirmado.", ephemeral=True)
            return

        actual_ids = {str(member.id) for member in confirmed_members}

        count_vou = sum(1 for r in respostas if r["resposta"] == "vou")
        count_talvez = sum(1 for r in respostas if r["resposta"] == "talvez")
        count_nao = sum(1 for r in respostas if r["resposta"] == "nao")

        awarded_count = 0
        awarded_details = []
        promotions = []
        config = db.get_config(server_id)

        for discord_id in actual_ids:
            username = discord_id
            member = interaction.guild.get_member(int(discord_id)) if discord_id.isdigit() else None
            if member:
                username = str(member)
            try:
                db.create_or_update_user(server_id, discord_id, username)
                db.add_xp(server_id, discord_id, xp_amount, "evento", f"Evento confirmado: {treino['descricao'][:64]}")
                awarded_count += 1
                mention = member.mention if member else f"<@{discord_id}>"
                awarded_details.append(f"{mention} — {xp_amount} XP")
                if member:
                    promotion_info = await check_promotion(interaction.guild, member, config)
                    if promotion_info:
                        promotions.append(f"{mention} -> {promotion_info['role_name']}")
            except Exception:
                pass

        for resposta in respostas:
            participou = resposta["discord_id"] in actual_ids
            db.mark_treino_participacao(treino_id, resposta["discord_id"], participou, xp_amount if participou else 0)

        db.finalize_treino(treino_id)

        # Editar mensagem original do evento para finalizar e remover botões
        if treino.get("canal_id") and treino.get("mensagem_id"):
            try:
                channel = interaction.guild.get_channel(int(treino["canal_id"]))
                if channel:
                    event_message = await channel.fetch_message(int(treino["mensagem_id"]))
                    final_embed = discord.Embed(
                        title="🏆 Evento Finalizado",
                        description=treino.get("descricao", ""),
                        color=BOT_COLOR
                    )
                    final_embed.add_field(name="ID do Evento", value=str(treino_id), inline=True)
                    final_embed.add_field(name="Participaram", value=str(count_vou), inline=True)
                    final_embed.add_field(name="Talvez", value=str(count_talvez), inline=True)
                    final_embed.add_field(name="Não vão", value=str(count_nao), inline=True)
                    final_embed.add_field(name="Confirmados", value=str(awarded_count), inline=True)
                    final_embed.add_field(name="XP por participante", value=str(xp_amount), inline=True)
                    final_embed.set_footer(text="Evento finalizado")
                    await event_message.edit(embed=final_embed, view=None)
            except Exception:
                pass

        log_embed = discord.Embed(
            title="Resultado de Evento Registrado",
            description=self.resultado.value,
            color=BOT_COLOR
        )
        log_embed.add_field(name="Evento", value=treino.get("titulo", treino.get("descricao", "Sem título")), inline=False)
        log_embed.add_field(name="ID do Evento", value=str(treino_id), inline=True)
        log_embed.add_field(name="Participaram", value=str(count_vou), inline=True)
        log_embed.add_field(name="Talvez", value=str(count_talvez), inline=True)
        log_embed.add_field(name="Não vão", value=str(count_nao), inline=True)
        log_embed.add_field(name="Confirmados", value=str(awarded_count), inline=True)
        log_embed.add_field(name="XP por participante", value=str(xp_amount), inline=True)

        if awarded_details:
            details_text = "\n".join(awarded_details[:10])
            if len(awarded_details) > 10:
                details_text += f"\n...e mais {len(awarded_details) - 10}"
            log_embed.add_field(name="XP distribuído", value=details_text, inline=False)

        if promotions:
            promotions_text = "\n".join(promotions[:10])
            if len(promotions) > 10:
                promotions_text += f"\n...e mais {len(promotions) - 10}"
            log_embed.add_field(name="Promoções geradas", value=promotions_text, inline=False)

        if respostas:
            vou_users = [r for r in respostas if r["resposta"] == "vou"]
            talvez_users = [r for r in respostas if r["resposta"] == "talvez"]
            nao_users = [r for r in respostas if r["resposta"] == "nao"]

            if vou_users:
                user_mentions = []
                for r in vou_users[:10]:
                    member = interaction.guild.get_member(int(r["discord_id"])) if r["discord_id"].isdigit() else None
                    user_mentions.append(member.mention if member else f"<@{r['discord_id']}>")
                if len(vou_users) > 10:
                    user_mentions.append(f"...e mais {len(vou_users) - 10}")
                log_embed.add_field(name="✅ Participaram", value="\n".join(user_mentions), inline=False)

            if talvez_users:
                user_mentions = []
                for r in talvez_users[:10]:
                    member = interaction.guild.get_member(int(r["discord_id"])) if r["discord_id"].isdigit() else None
                    user_mentions.append(member.mention if member else f"<@{r['discord_id']}>")
                if len(talvez_users) > 10:
                    user_mentions.append(f"...e mais {len(talvez_users) - 10}")
                log_embed.add_field(name="❔ Talvez", value="\n".join(user_mentions), inline=False)

            if nao_users:
                user_mentions = []
                for r in nao_users[:10]:
                    member = interaction.guild.get_member(int(r["discord_id"])) if r["discord_id"].isdigit() else None
                    user_mentions.append(member.mention if member else f"<@{r['discord_id']}>")
                if len(nao_users) > 10:
                    user_mentions.append(f"...e mais {len(nao_users) - 10}")
                log_embed.add_field(name="❌ Não vão", value="\n".join(user_mentions), inline=False)

        log_embed.set_footer(text=f"Registrado por {interaction.user.display_name}")
        await send_log(interaction.guild, "evento", embed=log_embed)

        treino_channel = None
        if treino.get("canal_id"):
            treino_channel = interaction.guild.get_channel(int(treino["canal_id"]))

        if treino_channel:
            result_embed = discord.Embed(
                title="🏆 Evento Finalizado",
                description=treino.get("descricao", ""),
                color=BOT_COLOR
            )
            result_embed.add_field(name="Resultado", value=self.resultado.value, inline=False)
            result_embed.add_field(name="ID do Evento", value=str(treino_id), inline=True)
            result_embed.add_field(name="Participaram", value=str(count_vou), inline=True)
            result_embed.add_field(name="Talvez", value=str(count_talvez), inline=True)
            result_embed.add_field(name="Não vão", value=str(count_nao), inline=True)
            result_embed.add_field(name="Confirmados", value=str(awarded_count), inline=True)
            result_embed.add_field(name="XP por participante", value=str(xp_amount), inline=True)
            if awarded_details:
                details_text = "\n".join(awarded_details[:15])
                if len(awarded_details) > 15:
                    details_text += f"\n...e mais {len(awarded_details) - 15}"
                result_embed.add_field(name="XP distribuído", value=details_text, inline=False)
            if promotions:
                promotions_text = "\n".join(promotions[:10])
                if len(promotions) > 10:
                    promotions_text += f"\n...e mais {len(promotions) - 10}"
                result_embed.add_field(name="Promoções geradas", value=promotions_text, inline=False)
            result_embed.set_footer(text=f"Registrado por {interaction.user.display_name}")
            await treino_channel.send(embed=result_embed)

        await interaction.response.send_message(f"✅ Resultado registrado. {awarded_count} participantes receberam {xp_amount} XP.", ephemeral=True)

@bot.tree.command(name="resultadoevento", description="Registra resultado de um evento e distribui XP")
async def resultadoevento(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return
    await interaction.response.send_modal(ResultadoEventoModal(interaction))

@bot.tree.command(name="set_inactivity_channel", description="Define o canal para encaminhar respostas de inatividade (staff)")
@app_commands.describe(channel="Canal para receber respostas de inatividade")
async def set_inactivity_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return

    server_id = str(interaction.guild.id)
    config = db.get_config(server_id)
    config["canal_inatividade"] = str(channel.id)
    db.save_config(config)

    await interaction.response.send_message(f"✅ Canal de inatividade definido como {channel.mention}.", ephemeral=True)

@bot.tree.command(name="set_message_points", description="Define quantos XP por mensagem no chat (staff)")
@app_commands.describe(amount="Quantidade de XP por mensagem")
async def set_message_points(interaction: discord.Interaction, amount: int):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return

    if amount < 0:
        await interaction.response.send_message("❌ O valor precisa ser zero ou positivo.", ephemeral=True)
        return

    server_id = str(interaction.guild.id)
    config = db.get_config(server_id)
    config["pontos_por_msg"] = amount
    db.save_config(config)

    await interaction.response.send_message(f"✅ XP por mensagem definidos para {amount}.", ephemeral=True)

@bot.tree.command(name="last_active", description="Mostra quando um usuário falou por último")
@app_commands.describe(user="Usuário para verificar")
async def last_active(interaction: discord.Interaction, user: discord.Member):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return

    server_id = str(interaction.guild.id)
    last_activity = db.get_last_activity(server_id, str(user.id))
    if not last_activity:
        await interaction.response.send_message(f"❌ Sem registro de atividade para {user.mention}.", ephemeral=True)
        return

    last_active_dt = datetime.fromtimestamp(last_activity)
    delta = datetime.now() - last_active_dt
    await interaction.response.send_message(
        f"✅ {user.mention} teve atividade pela última vez {discord.utils.format_dt(last_active_dt, style='R')} ({delta.days}d {delta.seconds // 3600}h { (delta.seconds % 3600) // 60 }m atrás).",
        ephemeral=True
    )

@bot.tree.command(name="inactive", description="Mostra usuários inativos")
@app_commands.describe(minutes="Minutos sem atividade")
async def inactive(interaction: discord.Interaction, minutes: int = 60):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return

    if minutes <= 0:
        await interaction.response.send_message("❌ O valor precisa ser maior que zero.", ephemeral=True)
        return

    server_id = str(interaction.guild.id)
    inactive_seconds = minutes * 60
    users = db.get_inactive_users(server_id, inactive_seconds)
    if not users:
        await interaction.response.send_message(f"✅ Nenhum usuário inativo por mais de {minutes} minutos.", ephemeral=True)
        return

    lines = []
    for user_data in users[:25]:
        member = interaction.guild.get_member(int(user_data["discord_id"]))
        if not member:
            continue
        last_active_dt = datetime.fromtimestamp(user_data["ultimo_atividade"])
        lines.append(f"{member.mention} — {discord.utils.format_dt(last_active_dt, style='R')}")

    if not lines:
        await interaction.response.send_message(f"✅ Nenhum usuário inativo por mais de {minutes} minutos encontrado no servidor.", ephemeral=True)
        return

    await interaction.response.send_message(
        "Usuarios inativos:\n" + "\n".join(lines[:25]),
        ephemeral=True
    )

def format_elapsed_time(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}min"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    if seconds < 30 * 86400:
        return f"{seconds // 86400}d"
    if seconds < 365 * 86400:
        return f"{seconds // (30 * 86400)}mês"
    return f"{seconds // (365 * 86400)}ano"

def build_activity_embeds(title: str, header: str, lines: list[str], color: discord.Color) -> list[discord.Embed]:
    embeds = []
    description = header
    for line in lines:
        next_description = f"{description}{line}\n"
        if len(next_description) > 3800:
            embeds.append(discord.Embed(title=title, description=description, color=color))
            description = f"{line}\n"
        else:
            description = next_description

    if description:
        embeds.append(discord.Embed(title=title, description=description, color=color))
    return embeds

@bot.tree.command(name="activity_status", description="Mostra status de atividade em eventos e em chat")
async def activity_status(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return

    server_id = str(interaction.guild.id)
    now_ts = int(datetime.now().timestamp())
    members = sorted(interaction.guild.members, key=lambda m: m.display_name.lower())
    if not members:
        await interaction.response.send_message("❌ Não foi possível encontrar membros no servidor.", ephemeral=True)
        return

    embed = discord.Embed(
        title="📊 Status de Atividade",
        description="Relatório de atividade dos membros no servidor.",
        color=discord.Color.blue()
    )

    # Atividade em Chat
    chat_lines = []
    for member in members[:20]:  # Limitar para não exceder limite de embed
        user_activity = db.get_last_activity(server_id, str(member.id))
        if user_activity and user_activity > 0:
            inactivity = now_ts - user_activity
            if inactivity >= 3 * 24 * 60 * 60:
                status = "🔴"
            elif inactivity > 2 * 24 * 60 * 60:
                status = "🟡"
            else:
                status = "🟢"
            chat_lines.append(f"{status} {member.mention} — {format_elapsed_time(inactivity)}")
        else:
            chat_lines.append(f"⚪ {member.mention} — Sem registro")

    embed.add_field(
        name="💬 Atividade em Chat",
        value="🟢 Até 2 dias — ativo.\n🟡 Entre 2 e 3 dias — atenção.\n🔴 3 dias ou mais — inativo.\n⚪ Sem registro — sem atividade registrada.\n\n" + "\n".join(chat_lines[:15]),
        inline=False
    )

    # Atividade em Eventos
    event_lines = []
    for member in members[:20]:  # Limitar para não exceder limite de embed
        event_activity = db.get_last_event_activity(server_id, str(member.id))
        if event_activity:
            resposta_ts = int(datetime.fromisoformat(event_activity["resposta_criado_em"]).timestamp())
            inactivity = now_ts - resposta_ts
            if inactivity <= 7 * 24 * 60 * 60:
                status = "🟢"
            elif inactivity <= 14 * 24 * 60 * 60:
                status = "🟡"
            else:
                status = "🔴"
            titulo = event_activity["titulo"][:20] + "..." if len(event_activity["titulo"]) > 20 else event_activity["titulo"]
            event_lines.append(f"{status} {member.mention} — último evento: {titulo} — {format_elapsed_time(inactivity)}")
        else:
            event_lines.append(f"⚪ {member.mention} — Sem registro")

    embed.add_field(
        name="🏆 Atividade em Eventos",
        value="🟢 Participou recentemente — ativo.\n🟡 Participou há alguns dias — atenção.\n🔴 Muito tempo sem participar — inativo.\n⚪ Sem registro — sem participação registrada.\n\n" + "\n".join(event_lines[:15]),
        inline=False
    )

    embed.set_footer(text=f"Total de membros: {len(members)} | Atualizado em {datetime.now().strftime('%H:%M')}")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tasks.loop(minutes=1)
async def lembrete_task():
    try:
        treinos = db.get_treinos_para_lembrete()
        now = datetime.now()

        for treino in treinos:
            if not treino["horario_inicio"]:
                continue

            try:
                horario = datetime.fromisoformat(treino["horario_inicio"])
            except:
                continue

            config = db.get_config(treino["server_id"])
            minutos_antes = config.get("lembrete_treino_minutos", 30)
            lembrete_time = horario - timedelta(minutes=minutos_antes)

            if now >= lembrete_time:
                # Enviar lembrete
                respostas = db.get_treino_respostas(treino["id"])
                vou_talvez = [r for r in respostas if r["resposta"] in ["vou", "talvez"]]

                embed = discord.Embed(
                    title="⏰ Lembrete de Treino",
                    description=f"Lembrete: o treino '{treino['titulo']}' começa em breve.",
                    color=discord.Color.orange()
                )

                count = 0
                for resposta in vou_talvez:
                    try:
                        user = await bot.fetch_user(int(resposta["discord_id"]))
                        await user.send(embed=embed)
                        count += 1
                    except:
                        pass

                # Marcar como enviado
                db.mark_lembrete_enviado(treino["id"])
                print(f"Lembrete enviado para {count} usuários do treino {treino['id']}")

    except Exception as e:
        print(f"Erro no lembrete_task: {e}")

def run_bot():
    if DISCORD_BOT_TOKEN:
        bot.run(DISCORD_BOT_TOKEN)
    else:
        print("DISCORD_BOT_TOKEN não configurado")
