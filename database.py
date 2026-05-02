import sqlite3
from datetime import datetime
from typing import List, Dict, Optional, Any
from config import DB_PATH
from discord_api import DiscordAPI
import json
import os

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
                    canal_inatividade TEXT,
                    canal_logs_treino TEXT,
                    pontos_por_treino INTEGER DEFAULT 2,
                    cargo_verificado TEXT,
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
                    ultimo_atividade INTEGER DEFAULT 0,
                    ultimo_inatividade_3d INTEGER DEFAULT 0,
                    ultimo_inatividade_7d INTEGER DEFAULT 0,
                    rebaixado_inativo INTEGER DEFAULT 0,
                    treino_confirmado INTEGER DEFAULT 0,
                    UNIQUE(server_id, discord_id)
                )
            """)

            # Adicionar coluna treino_confirmado se não existir
            try:
                cursor.execute("ALTER TABLE usuarios ADD COLUMN treino_confirmado INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # Coluna já existe

            # Adicionar coluna ultimo_atividade se não existir
            try:
                cursor.execute("ALTER TABLE usuarios ADD COLUMN ultimo_atividade INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # Coluna já existe

            # Adicionar coluna ultimo_inatividade_3d se não existir
            try:
                cursor.execute("ALTER TABLE usuarios ADD COLUMN ultimo_inatividade_3d INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            # Adicionar coluna ultimo_inatividade_7d se não existir
            try:
                cursor.execute("ALTER TABLE usuarios ADD COLUMN ultimo_inatividade_7d INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            # Adicionar coluna rebaixado_inativo se não existir
            try:
                cursor.execute("ALTER TABLE usuarios ADD COLUMN rebaixado_inativo INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass

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
                cursor.execute("ALTER TABLE configuracoes ADD COLUMN canal_inatividade TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE configuracoes ADD COLUMN canal_logs_treino TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE configuracoes ADD COLUMN pontos_por_treino INTEGER DEFAULT 2")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE configuracoes ADD COLUMN cargo_verificado TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE treinos ADD COLUMN pontos INTEGER DEFAULT 2")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE treinos ADD COLUMN target_role_id TEXT")
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
            try:
                cursor.execute("ALTER TABLE treino_respostas ADD COLUMN participou INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE treino_respostas ADD COLUMN pontos_concedidos INTEGER DEFAULT 0")
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
                    pontos INTEGER DEFAULT 2,
                    target_role_id TEXT,
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
                    participou INTEGER DEFAULT 0,
                    pontos_concedidos INTEGER DEFAULT 0,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(treino_id, discord_id)
                )
            """)

            # Tabela de config_canais (dinâmica)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS config_canais (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id TEXT NOT NULL,
                    nome TEXT NOT NULL,
                    tipo TEXT NOT NULL,
                    canal_id TEXT,
                    obrigatorio INTEGER DEFAULT 0,
                    ordem INTEGER DEFAULT 0,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(server_id, tipo)
                )
            """)

            # Tabela de patentes (dinâmica)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS patentes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id TEXT NOT NULL,
                    nome TEXT NOT NULL,
                    role_id TEXT,
                    xp_necessario INTEGER DEFAULT 0,
                    ordem INTEGER DEFAULT 0,
                    pode_excluir INTEGER DEFAULT 1,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.commit()

    def _load_backup_config(self, server_id: str) -> Optional[Dict[str, Any]]:
        backup_file = os.path.join(os.path.dirname(self.db_path), "backups", f"config_{server_id}.json")
        if os.path.exists(backup_file):
            try:
                with open(backup_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    print(f"Config carregada do backup para server_id: {server_id}")
                    return config
            except Exception as e:
                print(f"Erro ao carregar backup: {e}")
        return None

    def get_config(self, server_id: str) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM configuracoes WHERE server_id = ?", (server_id,))
            row = cursor.fetchone()
            if row:
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, row))
            # Tentar carregar do backup
            backup_config = self._load_backup_config(server_id)
            if backup_config:
                # Salvar no banco para restaurar
                self.save_config(backup_config)
                return backup_config
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
                "canal_inatividade": None,
                "canal_logs_treino": None,
                "pontos_por_treino": 2,
                "cargo_verificado": None,
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

    def _backup_config(self, config: Dict[str, Any]):
        backup_dir = os.path.join(os.path.dirname(self.db_path), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        backup_file = os.path.join(backup_dir, f"config_{config['server_id']}.json")
        try:
            with open(backup_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Erro ao fazer backup da config: {e}")

    def save_config(self, config: Dict[str, Any]) -> bool:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO configuracoes (
                        server_id, canal_avaliacao, canal_registro, canal_logs,
                        cargo_recruta, cargo_soldado, cargo_cabo, cargo_sargento,
                        cargo_ping_treinos, canal_treinos, canal_inatividade, canal_logs_treino,
                        pontos_por_treino, cargo_verificado,
                        lembrete_treino_minutos, dm_treinos,
                        xp_soldado, xp_cabo, xp_sargento, pontos_por_msg,
                        pontos_por_registro, cooldown_msg, auto_promover,
                        precisa_aprovacao, sistema_ativo, usar_dm, usar_ia
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    config["server_id"], config.get("canal_avaliacao"), config.get("canal_registro"),
                    config.get("canal_logs"), config.get("cargo_recruta"), config.get("cargo_soldado"),
                    config.get("cargo_cabo"), config.get("cargo_sargento"), config.get("cargo_ping_treinos"),
                    config.get("canal_treinos"), config.get("canal_inatividade"), config.get("canal_logs_treino"),
                    config.get("pontos_por_treino", 2), config.get("cargo_verificado"),
                    config.get("lembrete_treino_minutos", 30), config.get("dm_treinos", 1),
                    config.get("xp_soldado", 100), config.get("xp_cabo", 300), config.get("xp_sargento", 600),
                    config.get("pontos_por_msg", 10), config.get("pontos_por_registro", 50),
                    config.get("cooldown_msg", 60), config.get("auto_promover", 1),
                    config.get("precisa_aprovacao", 1), config.get("sistema_ativo", 1), config.get("usar_dm", 1),
                    config.get("usar_ia", 0)
                ))
                conn.commit()
                # Fazer backup da config
                self._backup_config(config)
                print(f"Config salva e backup feito para server_id: {config['server_id']}")
                return True
        except Exception as e:
            print(f"Erro ao salvar config: {e}")
            return False

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

    def update_last_activity(self, server_id: str, discord_id: str, timestamp: Optional[int] = None) -> bool:
        if timestamp is None:
            timestamp = int(datetime.now().timestamp())
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE usuarios SET ultimo_atividade = ?
                WHERE server_id = ? AND discord_id = ?
            """, (timestamp, server_id, discord_id))
            conn.commit()
            return cursor.rowcount > 0

    def reset_inactivity_flags(self, server_id: str, discord_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE usuarios SET ultimo_inatividade_3d = 0, ultimo_inatividade_7d = 0, rebaixado_inativo = 0
                WHERE server_id = ? AND discord_id = ?
            """, (server_id, discord_id))
            conn.commit()
            return cursor.rowcount > 0

    def mark_inactivity_warning(self, server_id: str, discord_id: str, days: int) -> bool:
        column = None
        if days == 3:
            column = "ultimo_inatividade_3d"
        elif days == 7:
            column = "ultimo_inatividade_7d"
        else:
            return False

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE usuarios SET {column} = ? WHERE server_id = ? AND discord_id = ?", (int(datetime.now().timestamp()), server_id, discord_id))
            conn.commit()
            return cursor.rowcount > 0

    def mark_inactivity_demoted(self, server_id: str, discord_id: str) -> bool:
        timestamp = int(datetime.now().timestamp())
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE usuarios SET 
                    rebaixado_inativo = ?,
                    ultimo_inatividade_3d = ?,
                    ultimo_inatividade_7d = ?
                WHERE server_id = ? AND discord_id = ?
            """, (timestamp, timestamp, timestamp, server_id, discord_id))
            conn.commit()
            return cursor.rowcount > 0

    def get_last_activity(self, server_id: str, discord_id: str) -> Optional[int]:
        user = self.get_user(server_id, discord_id)
        if not user:
            return None
        return user.get("ultimo_atividade", 0)

    def get_inactive_users(self, server_id: str, inactive_seconds: int) -> List[Dict[str, Any]]:
        cutoff = int(datetime.now().timestamp()) - inactive_seconds
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM usuarios
                WHERE server_id = ? AND ultimo_atividade > 0 AND ultimo_atividade <= ?
                ORDER BY ultimo_atividade ASC
            """, (server_id, cutoff))
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in rows]

    def get_users_with_activity(self, server_id: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM usuarios WHERE server_id = ? AND ultimo_atividade > 0
            """, (server_id,))
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in rows]

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

    def get_stats(self, server_id: str) -> Dict[str, int]:
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM usuarios WHERE server_id = ?", (server_id,))
            total_membros = cursor.fetchone()[0] or 0

            cursor.execute(
                "SELECT COUNT(*) FROM registros WHERE server_id = ? AND tipo = 'promocao'", 
                (server_id,)
            )
            promocoes = cursor.fetchone()[0] or 0

            cursor.execute(
                "SELECT COUNT(*) FROM registros WHERE server_id = ? AND tipo = 'mensagem' AND DATE(criado_em) = DATE('now')",
                (server_id,)
            )
            mensagens_hoje = cursor.fetchone()[0] or 0

            cursor.execute(
                "SELECT COALESCE(SUM(xp), 0) FROM registros WHERE server_id = ?",
                (server_id,)
            )
            xp_distribuido = cursor.fetchone()[0] or 0

            return {
                "total_membros": int(total_membros),
                "promocoes": int(promocoes),
                "mensagens_hoje": int(mensagens_hoje),
                "xp_distribuido": int(xp_distribuido)
            }

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

    def create_treino(self, server_id: str, criado_por: str, titulo: str = "Treino", descricao: str = "", horario_inicio: str = "", canal_id: str = "", pontos: int = 2, target_role_id: str = "") -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO treinos (server_id, criado_por, titulo, descricao, horario_inicio, canal_id, pontos, target_role_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (server_id, criado_por, titulo, descricao, horario_inicio, canal_id, pontos, target_role_id))
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

    def get_treino_resposta(self, treino_id: int, discord_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM treino_respostas
                WHERE treino_id = ? AND discord_id = ?
                LIMIT 1
            """, (treino_id, discord_id))
            row = cursor.fetchone()
            if row:
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, row))
            return None

    def set_treino_resposta(self, treino_id: int, server_id: str, discord_id: str, resposta: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO treino_respostas (treino_id, server_id, discord_id, resposta, participou, pontos_concedidos)
                VALUES (?, ?, ?, ?, 0, 0)
            """, (treino_id, server_id, discord_id, resposta))
            conn.commit()

    def mark_treino_participacao(self, treino_id: int, discord_id: str, participou: bool, pontos_concedidos: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE treino_respostas
                SET participou = ?, pontos_concedidos = ?
                WHERE treino_id = ? AND discord_id = ?
            """, (1 if participou else 0, pontos_concedidos, treino_id, discord_id))
            conn.commit()
            return cursor.rowcount > 0

    def cancel_treino(self, treino_id: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE treinos SET status = 'cancelado' WHERE id = ?
            """, (treino_id,))
            conn.commit()

    def finalize_treino(self, treino_id: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE treinos SET status = 'finalizado' WHERE id = ?
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

    def get_config_canais(self, server_id: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM config_canais
                WHERE server_id = ?
                ORDER BY ordem ASC, id ASC
            """, (server_id,))
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_config_canal_by_tipo(self, server_id: str, tipo: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM config_canais
                WHERE server_id = ? AND tipo = ?
            """, (server_id, tipo))
            row = cursor.fetchone()
            if row:
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, row))
            return None

    def create_config_canal(self, server_id: str, nome: str, tipo: str, canal_id: Optional[str] = None, obrigatorio: int = 0, ordem: int = 0) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO config_canais (server_id, nome, tipo, canal_id, obrigatorio, ordem)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (server_id, nome, tipo, canal_id, int(obrigatorio), int(ordem)))
            conn.commit()
            return cursor.lastrowid

    def update_config_canal(self, canal_id: int, server_id: str, data: Dict[str, Any]) -> bool:
        allowed_keys = ["nome", "tipo", "canal_id", "obrigatorio", "ordem"]
        fields = []
        values = []
        for key in allowed_keys:
            if key in data:
                fields.append(f"{key} = ?")
                values.append(data[key])

        if not fields:
            return False

        values.extend([canal_id, server_id])
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                UPDATE config_canais SET {', '.join(fields)}
                WHERE id = ? AND server_id = ?
            """, tuple(values))
            conn.commit()
            return cursor.rowcount > 0

    def delete_config_canal(self, canal_id: int, server_id: str) -> Optional[bool]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT obrigatorio FROM config_canais
                WHERE id = ? AND server_id = ?
            """, (canal_id, server_id))
            row = cursor.fetchone()
            if not row:
                return None
            if row[0] == 1:
                return False

            cursor.execute("""
                DELETE FROM config_canais
                WHERE id = ? AND server_id = ?
            """, (canal_id, server_id))
            conn.commit()
            return cursor.rowcount > 0

    def ensure_default_canais(self, server_id: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM config_canais WHERE server_id = ?", (server_id,))
            total = cursor.fetchone()[0] or 0
            if total > 0:
                return

            defaults = [
                (server_id, "Avaliação", "avaliacao", None, 1, 1),
                (server_id, "Registro", "registro", None, 1, 2),
                (server_id, "Logs", "logs", None, 0, 3),
                (server_id, "Treinos", "treinos", None, 0, 4)
            ]
            cursor.executemany("""
                INSERT INTO config_canais (server_id, nome, tipo, canal_id, obrigatorio, ordem)
                VALUES (?, ?, ?, ?, ?, ?)
            """, defaults)
            conn.commit()

    def get_patentes(self, server_id: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM patentes
                WHERE server_id = ?
                ORDER BY ordem ASC, id ASC
            """, (server_id,))
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_patentes_ordenadas_por_xp(self, server_id: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM patentes
                WHERE server_id = ?
                ORDER BY xp_necessario ASC, ordem ASC, id ASC
            """, (server_id,))
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def create_patente(self, server_id: str, nome: str, role_id: Optional[str] = None, xp_necessario: int = 0, ordem: int = 0, pode_excluir: int = 1) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO patentes (server_id, nome, role_id, xp_necessario, ordem, pode_excluir)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (server_id, nome, role_id, int(xp_necessario), int(ordem), int(pode_excluir)))
            conn.commit()
            return cursor.lastrowid

    def update_patente(self, patente_id: int, server_id: str, data: Dict[str, Any]) -> bool:
        allowed_keys = ["nome", "role_id", "xp_necessario", "ordem", "pode_excluir"]
        fields = []
        values = []
        for key in allowed_keys:
            if key in data:
                fields.append(f"{key} = ?")
                values.append(data[key])

        if not fields:
            return False

        values.extend([patente_id, server_id])
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                UPDATE patentes SET {', '.join(fields)}
                WHERE id = ? AND server_id = ?
            """, tuple(values))
            conn.commit()
            return cursor.rowcount > 0

    def delete_patente(self, patente_id: int, server_id: str) -> Optional[bool]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT pode_excluir FROM patentes
                WHERE id = ? AND server_id = ?
            """, (patente_id, server_id))
            row = cursor.fetchone()
            if not row:
                return None
            if row[0] == 0:
                return False

            cursor.execute("""
                DELETE FROM patentes
                WHERE id = ? AND server_id = ?
            """, (patente_id, server_id))
            conn.commit()
            return cursor.rowcount > 0

    def ensure_default_patentes(self, server_id: str) -> Dict[str, Any]:
        """
        Cria as patentes padrão e seus cargos no Discord.
        
        Retorna:
        {
            "success": True/False,
            "created": True/False (True se foram criadas nesta chamada),
            "error": None ou string de erro,
            "roles_created": Dict com status de criação de cada cargo
        }
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM patentes WHERE server_id = ?", (server_id,))
            total = cursor.fetchone()[0] or 0
            if total > 0:
                return {
                    "success": True,
                    "created": False,
                    "error": None,
                    "roles_created": {}
                }

            # Nomes e dados das patentes padrão
            patente_defaults = [
                {"nome": "Recruta", "xp": 0, "ordem": 1, "pode_excluir": 0},
                {"nome": "Soldado", "xp": 100, "ordem": 2, "pode_excluir": 1},
                {"nome": "Cabo", "xp": 300, "ordem": 3, "pode_excluir": 1},
                {"nome": "Sargento", "xp": 600, "ordem": 4, "pode_excluir": 1}
            ]

            roles_created = {}
            rows_to_insert = []
            
            # Criar cargos no Discord para cada patente
            for patente in patente_defaults:
                nome = patente["nome"]
                role_result = DiscordAPI.ensure_discord_role(server_id, nome)
                roles_created[nome] = role_result
                
                if "error" in role_result:
                    # Se erro ao criar cargo, retornar erro
                    return {
                        "success": False,
                        "created": False,
                        "error": f"Erro ao criar cargo '{nome}': {role_result.get('message', 'Desconhecido')}",
                        "roles_created": roles_created
                    }
                
                role_id = role_result.get("id")
                rows_to_insert.append((
                    server_id,
                    nome,
                    role_id,
                    patente["xp"],
                    patente["ordem"],
                    patente["pode_excluir"]
                ))

            # Inserir todas as patentes com seus role_ids
            try:
                cursor.executemany("""
                    INSERT INTO patentes (server_id, nome, role_id, xp_necessario, ordem, pode_excluir)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, rows_to_insert)
                conn.commit()
                
                return {
                    "success": True,
                    "created": True,
                    "error": None,
                    "roles_created": roles_created
                }
            except Exception as e:
                return {
                    "success": False,
                    "created": False,
                    "error": f"Erro ao inserir patentes no banco: {str(e)}",
                    "roles_created": roles_created
                }

# Instância global
db = Database()
