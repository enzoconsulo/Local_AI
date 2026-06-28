from dotenv import load_dotenv
import psycopg2
import os
from loguru import logger
from pathlib import Path

# ATUALIZADO: Caminho blindado apontando para o ficheiro de dados
ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / "CHAVES_DADOS.env")

try:
    logger.info("Tentando conectar ao PostgreSQL...")
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        database=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD")
    )
    
    logger.success("Banco conectado com sucesso!")
    cur = conn.cursor()
    
    cur.execute("""
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema='public'
    """)
    
    tabelas = cur.fetchall()
    logger.info(f"Foram encontradas {len(tabelas)} tabelas no esquema público:")
    for tabela in tabelas:
        print(f" - {tabela[0]}")
        
    conn.close()

except Exception as e:
    logger.error(f"Erro ao conectar: {e}")