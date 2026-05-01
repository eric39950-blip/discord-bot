import sqlite3
from datetime import datetime
from typing import List, Dict, Optional, Any
from config import DB_PATH

class Database:
    def __init__(self, db_path: str = str(DB_PATH)):
        self.db_path = db_path
        self._create_tables()

    def _get_connection(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _create_tables(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Tabela de configurações
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS configuracoes (
                    server_id TEXT PRIMARY KEY,
                    canal_avaliacao TEXT,
                    canal_registro TEXT,
                    canal_logs TEXT,
                    cargo_recruta TEXT,
                    cargo_soldado TEXT,
                    cargo_cabo TEXT,
                    cargo_sargento TEXT,
                    cargo_ping_treinos TEXT,
                    canal_treinos TEXT,
                    lembrete_treino_minutos INTEGER DEFAULT 30,
                    dm_treinos INTEGER DEFAULT 1,
                    xp_soldado INTEGER DEFAULT 100,
                    xp_cabo INTEGER DEFAULT 300,
                    xp_sargento INTEGER DEFAULT 600,
                    pontos_por_msg INTEGER DEFAULT 10,
                    pontos_por_registro INTEGER DEFAULT 50,
                    cooldown_msg INTEGER DEFAULT 60,
                    auto_promover INTEGER DEFAULT 1,
                    precisa_aprovacao INTEGER DEFAULT 1,
                    sistema_ativo INTEGER DEFAULT 1,
                    usar_dm INTEGER DEFAULT 1,
                    usar_ia INTEGER DEFAULT 0
                )
            """)

            # Tabela de usuários
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id TEXT,
                    discord_id TEXT,
                    username TEXT,
                    xp INTEGER DEFAULT 0,
                    cargo_atual TEXT,
                    ultimo_xp_msg INTEGER DEFAULT 0,
                    treino_confirmado INTEGER DEFAULT 0,
                    UNIQUE(server_id, discord_id)
                )
            """)

            # Adicionar coluna treino_confirmado se não existir
            try:
                cursor.execute("ALTER TABLE usuarios ADD COLUMN treino_confirmado INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # Coluna já existe

            # Adicionar coluna cargo_ping_treinos se não existir
            try:
                cursor.execute("ALTER TABLE configuracoes ADD COLUMN cargo_ping_treinos TEXT")
            except sqlite3.OperationalError:
                pass  # Coluna já existe

            # Adicionar novos campos na config
            try:
                cursor.execute("ALTER TABLE configuracoes ADD COLUMN canal_treinos TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE configuracoes ADD COLUMN lembrete_treino_minutos INTEGER DEFAULT 30")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE configuracoes ADD COLUMN dm_treinos INTEGER DEFAULT 1")
            except sqlite3.OperationalError:
                pass

            # Tabela de registros
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS registros (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id TEXT,
                    discord_id TEXT,
                    tipo TEXT,
                    xp INTEGER,
                    motivo TEXT,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Tabela de treinos
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS treinos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id TEXT NOT NULL,
                    criado_por TEXT NOT NULL,
                    titulo TEXT DEFAULT 'Treino',
                    descricao TEXT,
                    horario_inicio TEXT,
                    canal_id TEXT,
                    mensagem_id TEXT,
                    status TEXT DEFAULT 'aberto',
                    lembrete_enviado INTEGER DEFAULT 0,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Tabela de treino_respostas
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS treino_respostas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    treino_id INTEGER NOT NULL,
                    server_id TEXT NOT NULL,
                    discord_id TEXT NOT NULL,
                    resposta TEXT NOT NULL,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(treino_id, discord_id)
                )
            """)

            conn.commit()

    def get_config(self, server_id: str) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM configuracoes WHERE server_id = ?", (server_id,))
            row = cursor.fetchone()
            if row:
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, row))
            # Config padrão
            return {
                "server_id": server_id,
                "canal_avaliacao": None,
                "canal_registro": None,
                "canal_logs": None,
                "cargo_recruta": None,
                "cargo_soldado": None,
                "cargo_cabo": None,
                "cargo_sargento": None,
                "cargo_ping_treinos": None,
                "canal_treinos": None,
                "lembrete_treino_minutos": 30,
                "dm_treinos": 1,
                "xp_soldado": 100,
                "xp_cabo": 300,
                "xp_sargento": 600,
                "pontos_por_msg": 10,
                "pontos_por_registro": 50,
                "cooldown_msg": 60,
                "auto_promover": 1,
                "precisa_aprovacao": 1,
                "sistema_ativo": 1,
                "usar_dm": 1,
                "usar_ia": 0
            }

    def save_config(self, config: Dict[str, Any]) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO configuracoes (
                    server_id, canal_avaliacao, canal_registro, canal_logs,
                    cargo_recruta, cargo_soldado, cargo_cabo, cargo_sargento,
                    xp_soldado, xp_cabo, xp_sargento, pontos_por_msg,
                    pontos_por_registro, cooldown_msg, auto_promover,
                    precisa_aprovacao, sistema_ativo, usar_dm, usar_ia
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                config["server_id"], config.get("canal_avaliacao"), config.get("canal_registro"),
                config.get("canal_logs"), config.get("cargo_recruta"), config.get("cargo_soldado"),
                config.get("cargo_cabo"), config.get("cargo_sargento"), config.get("xp_soldado", 100),
                config.get("xp_cabo", 300), config.get("xp_sargento", 600), config.get("pontos_por_msg", 10),
                config.get("pontos_por_registro", 50), config.get("cooldown_msg", 60), config.get("auto_promover", 1),
                config.get("precisa_aprovacao", 1), config.get("sistema_ativo", 1), config.get("usar_dm", 1),
                config.get("usar_ia", 0)
            ))
            conn.commit()
            return True

    def get_user(self, server_id: str, discord_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM usuarios WHERE server_id = ? AND discord_id = ?
            """, (server_id, discord_id))
            row = cursor.fetchone()
            if row:
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, row))
            return None

    def create_or_update_user(self, server_id: str, discord_id: str, username: str) -> Dict[str, Any]:
        user = self.get_user(server_id, discord_id)
        if user:
            # Atualizar username se mudou
            if user["username"] != username:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE usuarios SET username = ? WHERE server_id = ? AND discord_id = ?
                    """, (username, server_id, discord_id))
                    conn.commit()
            return user

        # Criar novo usuário
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO usuarios (server_id, discord_id, username)
                VALUES (?, ?, ?)
            """, (server_id, discord_id, username))
            conn.commit()

        return self.get_user(server_id, discord_id)

    def add_xp(self, server_id: str, discord_id: str, xp: int, tipo: str = "mensagem", motivo: str = "") -> Dict[str, Any]:
        user = self.get_user(server_id, discord_id)
        if not user:
            raise ValueError("Usuário não encontrado")

        new_xp = user["xp"] + xp

        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Atualizar XP
            cursor.execute("""
                UPDATE usuarios SET xp = ?, ultimo_xp_msg = ?
                WHERE server_id = ? AND discord_id = ?
            """, (new_xp, int(datetime.now().timestamp()), server_id, discord_id))

            # Registrar na tabela de registros
            cursor.execute("""
                INSERT INTO registros (server_id, discord_id, tipo, xp, motivo)
                VALUES (?, ?, ?, ?, ?)
            """, (server_id, discord_id, tipo, xp, motivo))

            conn.commit()

        user["xp"] = new_xp
        return user

    def update_user_role(self, server_id: str, discord_id: str, cargo: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE usuarios SET cargo_atual = ?
                WHERE server_id = ? AND discord_id = ?
            """, (cargo, server_id, discord_id))
            conn.commit()
            return cursor.rowcount > 0

    def get_ranking(self, server_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT discord_id, username, xp, cargo_atual
                FROM usuarios
                WHERE server_id = ?
                ORDER BY xp DESC
                LIMIT ?
            """, (server_id, limit))
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def reset_treino_confirmado(self, server_id: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE usuarios
                SET treino_confirmado = 0
                WHERE server_id = ?
            """, (server_id,))
            conn.commit()

    def set_treino_confirmado(self, server_id: str, discord_id: str, confirmado: bool):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE usuarios
                SET treino_confirmado = ?
                WHERE server_id = ? AND discord_id = ?
            """, (1 if confirmado else 0, server_id, discord_id))
            conn.commit()

    def get_treino_confirmados(self, server_id: str) -> List[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT discord_id
                FROM usuarios
                WHERE server_id = ? AND treino_confirmado = 1
            """, (server_id,))
            return [row[0] for row in cursor.fetchall()]

    def create_treino(self, server_id: str, criado_por: str, titulo: str = "Treino", descricao: str = "", horario_inicio: str = "", canal_id: str = "") -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO treinos (server_id, criado_por, titulo, descricao, horario_inicio, canal_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (server_id, criado_por, titulo, descricao, horario_inicio, canal_id))
            conn.commit()
            return cursor.lastrowid

    def get_treinos(self, server_id: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT t.*, 
                       COUNT(CASE WHEN tr.resposta = 'vou' THEN 1 END) as vou_count,
                       COUNT(CASE WHEN tr.resposta = 'talvez' THEN 1 END) as talvez_count,
                       COUNT(CASE WHEN tr.resposta = 'nao' THEN 1 END) as nao_count
                FROM treinos t
                LEFT JOIN treino_respostas tr ON t.id = tr.treino_id
                WHERE t.server_id = ?
                GROUP BY t.id
                ORDER BY t.criado_em DESC
            """, (server_id,))
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_treino(self, treino_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT t.*, 
                       COUNT(CASE WHEN tr.resposta = 'vou' THEN 1 END) as vou_count,
                       COUNT(CASE WHEN tr.resposta = 'talvez' THEN 1 END) as talvez_count,
                       COUNT(CASE WHEN tr.resposta = 'nao' THEN 1 END) as nao_count
                FROM treinos t
                LEFT JOIN treino_respostas tr ON t.id = tr.treino_id
                WHERE t.id = ?
                GROUP BY t.id
            """, (treino_id,))
            row = cursor.fetchone()
            if row:
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, row))
            return None

    def get_treino_respostas(self, treino_id: int) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM treino_respostas
                WHERE treino_id = ?
                ORDER BY criado_em DESC
            """, (treino_id,))
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def set_treino_resposta(self, treino_id: int, server_id: str, discord_id: str, resposta: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO treino_respostas (treino_id, server_id, discord_id, resposta)
                VALUES (?, ?, ?, ?)
            """, (treino_id, server_id, discord_id, resposta))
            conn.commit()

    def cancel_treino(self, treino_id: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE treinos SET status = 'cancelado' WHERE id = ?
            """, (treino_id,))
            conn.commit()

    def update_treino_mensagem(self, treino_id: int, mensagem_id: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE treinos SET mensagem_id = ? WHERE id = ?
            """, (mensagem_id, treino_id))
            conn.commit()

    def get_treinos_para_lembrete(self) -> List[Dict[str, Any]]:
        # Buscar treinos abertos com horário próximo e lembrete não enviado
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM treinos
                WHERE status = 'aberto' AND horario_inicio IS NOT NULL AND lembrete_enviado = 0
            """)
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def mark_lembrete_enviado(self, treino_id: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE treinos SET lembrete_enviado = 1 WHERE id = ?
            """, (treino_id,))
            conn.commit()

# Instância global
db = Database()
