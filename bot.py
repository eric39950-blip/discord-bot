import discord
from discord.ext import commands, tasks
import discord.app_commands as app_commands
import asyncio
from datetime import datetime, timedelta
from config import DISCORD_BOT_TOKEN
from database import db
from discord_api import DiscordAPI

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix=None, intents=intents, help_command=None)

async def send_log_embed(guild: discord.Guild, embed: discord.Embed):
    config = db.get_config(str(guild.id))
    canal_logs = config.get("canal_logs")
    if not canal_logs:
        return
    channel = guild.get_channel(int(canal_logs))
    if channel:
        try:
            await channel.send(embed=embed)
        except:
            pass

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

    @discord.ui.button(label="⚠️ Rejeições", style=discord.ButtonStyle.blurple)
    async def notif_rejections(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
            return
        
        await interaction.response.send_message(
            f"✅ Você será notificado sobre rejeições via DM!",
            ephemeral=True
        )

class TicketView(discord.ui.View):
    @discord.ui.button(label="🎫 Abrir Ticket", style=discord.ButtonStyle.primary)
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user

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
            title="🎫 Ticket Aberto",
            description=f"Olá {user.mention}, seu ticket foi aberto. Aguarde o suporte responder aqui.",
            color=discord.Color.green()
        )
        embed.add_field(name="Canal", value=channel.mention, inline=False)
        embed.set_footer(text="Somente você e staff com permissão podem ver este canal.")

        await channel.send(embed=embed)
        
        # Embed do formulário de verificação
        form_embed = discord.Embed(
            title="📋 Formulário de Verificação",
            description="Você deve fazer sua verificação para ter acesso ao nossa União! Complete o formulário abaixo com as informações solicitadas.",
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
        await send_log_embed(guild, log_embed)
        
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

class TreinoConfirmView(discord.ui.View):
    def __init__(self, treino_id: int, server_id: str, discord_id: str):
        super().__init__(timeout=None)
        self.treino_id = treino_id
        self.server_id = server_id
        self.discord_id = discord_id

    @discord.ui.button(label="✅ Vou", style=discord.ButtonStyle.success)
    async def confirm_vou(self, interaction: discord.Interaction, button: discord.ui.Button):
        db.set_treino_resposta(self.treino_id, self.server_id, self.discord_id, "vou")
        await interaction.response.send_message("✅ Resposta registrada: Vou!", ephemeral=True)

    @discord.ui.button(label="🤔 Talvez", style=discord.ButtonStyle.secondary)
    async def confirm_talvez(self, interaction: discord.Interaction, button: discord.ui.Button):
        db.set_treino_resposta(self.treino_id, self.server_id, self.discord_id, "talvez")
        await interaction.response.send_message("🤔 Resposta registrada: Talvez!", ephemeral=True)

    @discord.ui.button(label="❌ Não vou", style=discord.ButtonStyle.danger)
    async def confirm_nao(self, interaction: discord.Interaction, button: discord.ui.Button):
        db.set_treino_resposta(self.treino_id, self.server_id, self.discord_id, "nao")
        await interaction.response.send_message("❌ Resposta registrada: Não vou!", ephemeral=True)

@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")
    print(f"Servidores: {len(bot.guilds)}")
    await bot.tree.sync()

    # Iniciar task de lembretes
    lembrete_task.start()

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Se for um canal de ticket e a mensagem vier do dono do ticket, avisar somente se for o formulário
    if message.channel.name.startswith("ticket-"):
        try:
            ticket_owner_id = int(message.channel.name.replace("ticket-", ""))
        except ValueError:
            ticket_owner_id = None

        if ticket_owner_id and message.author.id == ticket_owner_id:
            content = message.content.lower()
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
            found = sum(1 for marker in marker if marker in content)

            if found >= 3:
                try:
                    await message.add_reaction("✅")
                    await message.reply(
                        "✅ Formulário recebido! Aguarde um membro da equipe revisar sua solicitação.",
                        mention_author=False
                    )
                except:
                    pass  # Ignorar erro de resposta

    # Comando +registro treino
    if message.content.lower() == "+registro treino":
        if not message.author.guild_permissions.manage_roles:
            await message.reply("❌ Você não tem permissão para registrar treinos.", mention_author=False)
            return

        server_id = str(message.guild.id)
        config = db.get_config(server_id)
    if config.get("sistema_ativo", 1) == 0:
        return

    # Criar treino
    treino_id = db.create_treino(server_id, str(message.author.id))
    treino = db.get_treino(treino_id)

    # Canal para mensagem
    canal_id = config.get("canal_treinos") or str(message.channel.id)
    channel = message.guild.get_channel(int(canal_id))
    if not channel:
        channel = message.channel

    embed = discord.Embed(
        title="🏋️ Treino Registrado!",
        description="Um novo treino foi registrado. Confirme se você vai participar:",
        color=discord.Color.blue()
    )
    embed.set_footer(text="Use os botões abaixo para confirmar presença.")

    view = TreinoConfirmView(treino_id, server_id, "")
    msg = await channel.send(embed=embed, view=view)
    db.update_treino_mensagem(treino_id, str(msg.id))

    # Enviar DM se ativado
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
                        except:
                            pass
                await message.reply(f"✅ Treino registrado! {count} membros notificados via DM.", mention_author=False)
            else:
                await message.reply("❌ Cargo de ping treinos não encontrado.", mention_author=False)
        else:
            await message.reply("❌ Cargo de ping treinos não configurado.", mention_author=False)
    else:
        await message.reply("✅ Treino registrado!", mention_author=False)
        confirmados = db.get_treino_confirmados(server_id)

        embed = discord.Embed(
            title="🏋️ Treino Iniciando!",
            description="O treino está começando agora! Preparem-se.",
            color=discord.Color.green()
        )

        count = 0
        for discord_id in confirmados:
            member = message.guild.get_member(int(discord_id))
            if member:
                try:
                    await member.send(embed=embed)
                    count += 1
                except:
                    pass

        await message.reply(f"✅ Treino iniciado! {count} membros confirmados notificados.", mention_author=False)

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
    embed = discord.Embed(title="Ajuda do Bot", description="Comandos disponíveis:")
    embed.add_field(name="/xp", value="Mostra seu XP atual", inline=False)
    embed.add_field(name="/ranking", value="Exibe o ranking de XP", inline=False)
    embed.add_field(name="/addxp", value="Adiciona XP a um usuário (staff)", inline=False)
    embed.add_field(name="/user", value="Ver perfil/XP de um usuário", inline=False)
    embed.add_field(name="/promote", value="Promover usuário manualmente (staff)", inline=False)
    embed.add_field(name="/demote", value="Rebaixar usuário (staff)", inline=False)
    embed.add_field(name="/clear-xp", value="Limpar XP de um usuário (staff)", inline=False)
    embed.add_field(name="/setup_ticket", value="Configura sistema de tickets (staff)", inline=False)
    embed.add_field(name="/setup_logs", value="Configura notificações de eventos (staff)", inline=False)
    embed.add_field(name="/close", value="Fecha ticket (staff)", inline=False)
    embed.add_field(name="/set_ping_treinos", value="Define cargo para ping de treinos (staff)", inline=False)
    embed.add_field(name="+registro treino", value="Registra treino e notifica membros (staff)", inline=False)
    await interaction.response.send_message(embed=embed)

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
    config = db.get_config(server_id)
    
    # Validar cargo
    valid_roles = ["recruta", "soldado", "cabo", "sargento"]
    if role.lower() not in valid_roles:
        await interaction.response.send_message(f"❌ Cargo inválido. Opções: {', '.join(valid_roles)}", ephemeral=True)
        return
    
    role_id = config.get(f"cargo_{role.lower()}")
    if not role_id:
        await interaction.response.send_message(f"❌ Cargo '{role}' não configurado no servidor.", ephemeral=True)
        return
    
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
    config = db.get_config(server_id)
    
    # Validar cargo
    valid_roles = ["recruta", "soldado", "cabo", "sargento"]
    if role.lower() not in valid_roles:
        await interaction.response.send_message(f"❌ Cargo inválido. Opções: {', '.join(valid_roles)}", ephemeral=True)
        return
    
    role_id = config.get(f"cargo_{role.lower()}")
    if not role_id:
        await interaction.response.send_message(f"❌ Cargo '{role}' não configurado.", ephemeral=True)
        return
    
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
        title="🎫 Sistema de Suporte",
        description="Clique no botão abaixo para abrir um ticket de suporte.",
        color=discord.Color.blue()
    )
    view = TicketView()
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="setup_logs", description="Configura notificações de eventos (staff)")
async def setup_logs(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        return

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
    
    server_id = str(interaction.guild.id)
    config = db.get_config(server_id)
    config["canal_logs"] = str(interaction.channel.id)
    db.save_config(config)

    embed.add_field(
        name="📍 Canal de Logs",
        value=f"Este canal foi definido como canal de logs para o servidor.",
        inline=False
    )
    embed.set_footer(text="Todos os eventos vão ser enviados aqui quando acontecerem.")

    view = LogsView(str(interaction.guild.id))
    await interaction.response.send_message(embed=embed, view=view)

    log_embed = discord.Embed(
        title="📌 Canal de Logs Configurado",
        description=f"Este canal foi definido como canal de logs por {interaction.user.mention}.",
        color=discord.Color.gold()
    )
    await send_log_embed(interaction.guild, log_embed)

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
