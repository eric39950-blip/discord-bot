import secrets
import requests
from flask import session, redirect
from typing import Optional, Dict, Any, List
from config import DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_REDIRECT_URI, FRONTEND_URL
from discord_api import DiscordAPI

class Auth:
    @staticmethod
    def generate_state() -> str:
        return secrets.token_urlsafe(32)

    @staticmethod
    def get_login_url() -> str:
        state = Auth.generate_state()
        session["oauth_state"] = state

        params = {
            "client_id": DISCORD_CLIENT_ID,
            "redirect_uri": DISCORD_REDIRECT_URI,
            "response_type": "code",
            "scope": "identify email guilds",
            "state": state,
            "prompt": "consent"
        }

        query = "&".join([f"{k}={v}" for k, v in params.items()])
        return f"https://discord.com/api/oauth2/authorize?{query}"

    @staticmethod
    def exchange_code(code: str) -> Optional[str]:
        data = {
            "client_id": DISCORD_CLIENT_ID,
            "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DISCORD_REDIRECT_URI
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        try:
            response = requests.post("https://discord.com/api/oauth2/token", data=data, headers=headers)
            if response.status_code != 200:
                print(f"[OAuth] token exchange failed: status={response.status_code}, body={response.text}")
            response.raise_for_status()
            token_data = response.json()
            return token_data.get("access_token")
        except requests.RequestException as exc:
            print(f"[OAuth] exchange_code request error: {exc}")
            return None

    @staticmethod
    def validate_state(state: str) -> bool:
        stored_state = session.get("oauth_state")
        valid = stored_state == state
        if not valid:
            print(f"[OAuth] invalid state: received={state!r} stored={stored_state!r}")
        return valid

    @staticmethod
    def login_user(access_token: str) -> bool:
        user = DiscordAPI.get_user(access_token)
        if user:
            session["access_token"] = access_token
            session["user"] = user
            session.permanent = True

            try:
                admin_guilds = Auth.get_user_servers()
                session["admin_guild_ids"] = [guild["id"] for guild in admin_guilds]
            except Exception as exc:
                print(f"[Auth] failed to populate admin_guild_ids: {exc}")
                session["admin_guild_ids"] = []

            return True
        return False

    @staticmethod
    def logout_user():
        session.pop("access_token", None)
        session.pop("user", None)
        session.pop("oauth_state", None)
        session.pop("admin_guild_ids", None)

    @staticmethod
    def get_current_user() -> Optional[Dict[str, Any]]:
        return session.get("user")

    @staticmethod
    def get_access_token() -> Optional[str]:
        return session.get("access_token")

    @staticmethod
    def is_logged_in() -> bool:
        return "access_token" in session and "user" in session

    @staticmethod
    def get_user_servers() -> List[Dict[str, Any]]:
        token = Auth.get_access_token()
        if not token:
            return []

        guilds = DiscordAPI.get_user_guilds(token)
        # Filtrar apenas servidores onde o usuário tem permissão ADMINISTRATOR
        admin_guilds = []
        for guild in guilds:
            permissions = int(guild.get("permissions", 0))
            if guild.get("owner") or (permissions & 0x8):  # ADMINISTRATOR permission
                admin_guilds.append({
                    "id": guild["id"],
                    "name": guild["name"],
                    "icon": guild.get("icon"),
                    "owner": guild.get("owner", False),
                    "permissions": permissions
                })

        return admin_guilds

    @staticmethod
    def can_manage_server(server_id: str) -> tuple[bool, str]:
        if not Auth.is_logged_in():
            return False, "not_logged_in"

        admin_guild_ids = session.get("admin_guild_ids")
        if admin_guild_ids is None:
            user_servers = Auth.get_user_servers()
            admin_guild_ids = [guild["id"] for guild in user_servers]

        if server_id not in admin_guild_ids:
            return False, "not_admin"

        if not DiscordAPI.is_bot_in_guild(server_id):
            return False, "bot_not_in_server"

        return True, "authorized"
