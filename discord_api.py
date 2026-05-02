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

    @staticmethod
    def create_role(guild_id: str, role_name: str) -> Optional[Dict[str, Any]]:
        """Cria um novo cargo no servidor"""
        payload = {
            "name": role_name,
            "permissions": 0,
            "hoist": False,
            "mentionable": False
        }
        return DiscordAPI._make_bot_request(f"/guilds/{guild_id}/roles", method="POST", json=payload)

    @staticmethod
    def ensure_discord_role(guild_id: str, role_name: str) -> Dict[str, Any]:
        """
        Garante que um cargo existe no servidor.
        Se existir, retorna seus dados.
        Se não existir, cria e retorna os dados.
        
        Retorna:
        {
            "id": "role_id",
            "name": "role_name",
            "created": True/False (True se foi criado nesta chamada)
        }
        
        Ou em caso de erro:
        {
            "error": "error_type",
            "message": "error_message"
        }
        """
        # Verificar se o bot está no servidor
        if not DiscordAPI.is_bot_in_guild(guild_id):
            return {"error": "bot_not_in_server", "message": "Bot não está no servidor"}

        # Procurar cargo existente com esse nome
        roles = DiscordAPI.get_guild_roles(guild_id)
        existing_role = next((r for r in roles if r.get("name") == role_name), None)
        
        if existing_role:
            return {
                "id": str(existing_role["id"]),
                "name": existing_role["name"],
                "created": False
            }

        # Tentar criar novo cargo
        new_role = DiscordAPI.create_role(guild_id, role_name)
        if not new_role:
            return {"error": "failed_to_create_role", "message": "Erro ao criar cargo no Discord"}

        return {
            "id": str(new_role["id"]),
            "name": new_role["name"],
            "created": True
        }
