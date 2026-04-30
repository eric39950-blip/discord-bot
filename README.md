# Discord Bot Dashboard Backend

Backend Flask + Discord.py para dashboard de configuração de bot Discord com sistema XP e promoções.

## Funcionalidades

- 🔐 Login Discord OAuth
- 🛡️ Validação de permissões admin por servidor
- 📊 Dashboard de configuração
- 🤖 Sistema XP automático
- 📈 Promoções automáticas/manuais
- 💾 SQLite para persistência

## Stack

- **Python 3.8+**
- **Flask** - API REST
- **discord.py** - Bot Discord
- **SQLite** - Banco de dados
- **Flask-CORS** - CORS para frontend
- **requests** - Chamadas HTTP

## Instalação

1. **Clone o repositório:**
   ```bash
   git clone <repo>
   cd backend
   ```

2. **Instale as dependências:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure as variáveis de ambiente:**
   ```bash
   cp .env.example .env
   # Edite o .env com suas configurações
   ```

## Configuração Discord

### 1. Criar aplicação no Discord Developer Portal

1. Acesse [Discord Developer Portal](https://discord.com/developers/applications)
2. Clique em "New Application"
3. Dê um nome ao seu bot

### 2. Configurar OAuth2

1. Vá para "OAuth2" > "General"
2. Em "Redirects", adicione:
   - Para desenvolvimento: `http://localhost:5000/callback`
   - Para produção: `https://seudominio.com/callback`

### 3. Obter tokens

1. **Client ID**: Na página principal da aplicação
2. **Client Secret**: Em "OAuth2" > "General"
3. **Bot Token**: Vá para "Bot" e clique em "Reset Token"

### 4. Configurar permissões do bot

Em "Bot" > "Bot Permissions", selecione:
- `bot`
- Permissões específicas:
  - Manage Roles
  - Send Messages
  - Read Messages
  - Read Message History
  - Use Slash Commands

### 5. Convidar o bot

Use esta URL para convidar o bot:
```
https://discord.com/api/oauth2/authorize?client_id=SEU_CLIENT_ID&permissions=268435456&scope=bot%20applications.commands
```

## Como rodar

### Desenvolvimento

1. **Instale python-dotenv:**
   ```bash
   pip install python-dotenv
   ```

2. **Configure o .env** com suas credenciais

3. **Execute o servidor:**
   ```bash
   python run.py
   ```

### Produção

Para produção, use um servidor WSGI como Gunicorn:

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

## Estrutura de arquivos

```
backend/
├── app.py              # Flask application
├── bot.py              # Discord bot
├── database.py         # SQLite database manager
├── discord_api.py      # Discord API helpers
├── auth.py             # OAuth2 authentication
├── config.py           # Configuration loader
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variables template
└── README.md           # This file
```

## API Endpoints

### Autenticação
- `GET /api/login_url` - URL de login Discord
- `GET /callback` - Callback OAuth2
- `GET /api/me` - Usuário logado
- `GET /api/logout` - Logout

### Servidores
- `GET /api/servers` - Lista servidores admin
- `GET /api/server/<id>/authorize` - Verifica permissão
- `GET /api/server/<id>/channels` - Canais do servidor
- `GET /api/server/<id>/roles` - Cargos do servidor

### Configuração
- `GET /api/config?server_id=<id>` - Carrega config
- `POST /api/config` - Salva config

### XP e Ranking
- `GET /api/ranking?server_id=<id>` - Ranking XP
- `POST /api/usuario/<discord_id>/xp` - Adiciona XP manual

## Deploy

### Railway
1. Conecte seu repositório Git
2. Configure as variáveis de ambiente
3. Railway detectará automaticamente o Flask

### Render
1. Crie um novo Web Service
2. Conecte o repositório
3. Configure build command: `pip install -r requirements.txt`
4. Configure start command: `gunicorn app:app`

### VPS
1. Instale Python 3.8+
2. Configure Nginx + Gunicorn
3. Use SSL (Let's Encrypt)

## Segurança

- ✅ Sessões seguras com HttpOnly
- ✅ Validação de state OAuth2
- ✅ CORS configurado apenas para frontend
- ✅ Verificação de permissões admin
- ✅ Nunca expõe BOT_TOKEN para frontend
- ✅ Sanitização de inputs

## Suporte

Para dúvidas ou problemas, abra uma issue no repositório.