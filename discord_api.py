import requests
from typing import List, Dict, Optional, Any
from config import DISCORD_BOT_TOKEN

class DiscordAPI:
    BASE_URL = "https://discord.com/api/v10"

    @staticmethod
    def _make_request(endpoint: str, token: str, method: str = "GET", **kwargs) -> Optional[Dict]:
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{DiscordAPI.BASE_URL}{endpoint}"

        try:
            response = requests.request(method, url, headers=headers, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.RequestException:
            return None

    @staticmethod
    def _make_bot_request(endpoint: str, method: str = "GET", **kwargs) -> Optional[Dict]:
        headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
        url = f"{DiscordAPI.BASE_URL}{endpoint}"

        try:
            response = requests.request(method, url, headers=headers, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.RequestException:
            return None

    @staticmethod
    def get_user(token: str) -> Optional[Dict[str, Any]]:
        return DiscordAPI._make_request("/users/@me", token)

    @staticmethod
    def get_user_guilds(token: str) -> List[Dict[str, Any]]:
        guilds = DiscordAPI._make_request("/users/@me/guilds", token)
        return guilds if guilds else []

    @staticmethod
    def get_guild_channels(guild_id: str) -> List[Dict[str, Any]]:
        channels = DiscordAPI._make_bot_request(f"/guilds/{guild_id}/channels")
        if not channels:
            return []

        # Filtrar apenas canais de texto (type 0) e anúncios (type 5)
        return [ch for ch in channels if ch.get("type") in [0, 5]]

    @staticmethod
    def get_guild_roles(guild_id: str) -> List[Dict[str, Any]]:
        roles = DiscordAPI._make_bot_request(f"/guilds/{guild_id}/roles")
        if not roles:
            return []

        # Remover @everyone e ordenar por posição
        filtered = [r for r in roles if not r.get("name") == "@everyone"]
        return sorted(filtered, key=lambda x: x.get("position", 0), reverse=True)

    @staticmethod
    def is_bot_in_guild(guild_id: str) -> bool:
        # Verificar se o bot está no servidor
        guild = DiscordAPI._make_bot_request(f"/guilds/{guild_id}")
        return guild is not None