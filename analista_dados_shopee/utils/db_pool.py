"""
utils/db_pool.py
================
Pool de conexões PostgreSQL thread-safe compartilhado entre todas as páginas
Streamlit e workers. Elimina o overhead de abrir/fechar uma conexão por
requisição — crítico no Streamlit, onde cada interação re-executa a página.

USO BÁSICO
----------
    from utils.db_pool import get_connection

    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM dim_produtos WHERE status_shopee = 'NORMAL'")
            rows = cur.fetchall()
    # commit automático ao sair; rollback automático se lançar exceção

HELPERS PRONTOS
---------------
    df   = query_df("SELECT ...")              → pandas DataFrame (≤500 linhas)
    row  = query_one("SELECT ... LIMIT 1")    → dict ou None
    n    = execute("INSERT INTO ...")          → rowcount
    n    = executemany("INSERT ...", lista)    → rowcount (execute_values)

CONFIGURAÇÃO
------------
    Lê DB_HOST, DB_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
    do arquivo CHAVES_DADOS.env na raiz do projeto.

    Para ajustar o tamanho do pool, altere MIN_CONN / MAX_CONN abaixo.
    Regra geral: MAX_CONN ≤ max_connections do PostgreSQL / nº de workers.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
from psycopg2.extras import execute_values
from psycopg2.pool import ThreadedConnectionPool
from dotenv import load_dotenv
from loguru import logger

# ── Configuração ───────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / "CHAVES_DADOS.env")

MIN_CONN: int = 2    # Conexões abertas ao iniciar
MAX_CONN: int = 12   # Teto de conexões simultâneas
STMT_TIMEOUT_MS: int = 30_000  # 30 s — mata queries travadas automaticamente

# ── Singleton thread-safe ─────────────────────────────────────────────────────
_pool: ThreadedConnectionPool | None = None
_lock = threading.Lock()


def _build_pool() -> ThreadedConnectionPool:
    """Cria o pool com os parâmetros do .env e opções de segurança."""
    return ThreadedConnectionPool(
        minconn=MIN_CONN,
        maxconn=MAX_CONN,
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5433")),
        database=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        connect_timeout=10,
        # statement_timeout mata queries longas; application_name aparece no pg_stat_activity
        options=f"-c statement_timeout={STMT_TIMEOUT_MS} -c application_name=shopee_dw",
    )


def _get_pool() -> ThreadedConnectionPool:
    """Retorna (ou cria) o pool singleton de forma thread-safe (double-checked locking)."""
    global _pool
    if _pool is None or _pool.closed:
        with _lock:
            if _pool is None or _pool.closed:
                logger.info("🔌 Inicializando pool de conexões PostgreSQL...")
                _pool = _build_pool()
                logger.success(f"Pool criado (min={MIN_CONN}, max={MAX_CONN}).")
    return _pool


# ── Context manager principal ─────────────────────────────────────────────────

@contextmanager
def get_connection():
    """
    Empresta uma conexão do pool, faz commit ao sair e rollback se houver erro.

    Exemplo:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("SELECT * FROM dim_variacoes WHERE item_id = %s", (123,))
                rows = cur.fetchall()
    """
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


# ── Helpers de alto nível ─────────────────────────────────────────────────────

def query_df(sql: str, params: tuple | None = None, max_rows: int = 500):
    """
    Executa um SELECT e retorna um pandas DataFrame.
    Limitado a max_rows para proteger a memória do Streamlit.

    Exemplo:
        df = query_df(
            "SELECT * FROM vw_saude_produto ORDER BY vendas_7d DESC",
            max_rows=100
        )
    """
    import pandas as pd

    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, params)
            if cur.description:
                cols = [d[0] for d in cur.description]
                rows = cur.fetchmany(max_rows)
                return pd.DataFrame(rows, columns=cols)
    return __import__("pandas").DataFrame()


def query_one(sql: str, params: tuple | None = None) -> dict[str, Any] | None:
    """
    Executa um SELECT e retorna a primeira linha como dict, ou None.

    Exemplo:
        ultima = query_one(
            "SELECT data_fim_coleta FROM sys_controle_sync "
            "WHERE modulo = %s AND status = 'SUCESSO' "
            "ORDER BY data_fim_coleta DESC LIMIT 1",
            ("PEDIDOS",)
        )
        data = ultima["data_fim_coleta"] if ultima else None
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None


def query_all(sql: str, params: tuple | None = None) -> list[dict[str, Any]]:
    """
    Executa um SELECT e retorna todas as linhas como lista de dicts.
    Use com parcimônia — prefira query_df para conjuntos grandes.
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


def execute(sql: str, params: tuple | None = None) -> int:
    """
    Executa um INSERT / UPDATE / DELETE e retorna rowcount.

    Exemplo:
        execute(
            "UPDATE dim_materiais SET estoque_atual = %s WHERE id_material = %s",
            (42.5, 3)
        )
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount


def bulk_insert(sql: str, rows: list[tuple], page_size: int = 1000) -> int:
    """
    Insere múltiplas linhas usando psycopg2.extras.execute_values (muito mais
    rápido que executemany para lotes grandes).

    Exemplo:
        bulk_insert(
            "INSERT INTO fato_trafego_diario (item_id, data, visitantes_unicos) VALUES %s",
            [(123, "2026-06-01", 50), (124, "2026-06-01", 30)]
        )
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            execute_values(cur, sql, rows, page_size=page_size)
            return cur.rowcount


# ── Diagnóstico (útil no test_db.py e no pgAdmin) ────────────────────────────

def pool_status() -> dict:
    """Retorna métricas do pool para debug."""
    pool = _get_pool()
    return {
        "fechado": pool.closed,
        "min_conn": MIN_CONN,
        "max_conn": MAX_CONN,
    }
