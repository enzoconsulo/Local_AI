"""
init_db/aplicar_migrations.py
=============================
Aplicador idempotente das migrações do Data Warehouse.

Por que existe: as migrações eram aplicadas manualmente (pgAdmin/psql) e era
fácil esquecer uma — o app degrada silenciosamente sem as views/colunas novas
(a página 3 chega a bloquear a auditoria se a migração 12 faltar). Este runner
dá um único comando confiável:

    python init_db/aplicar_migrations.py            # mostra o plano e aplica as pendentes
    python init_db/aplicar_migrations.py --status   # só mostra o estado, não aplica nada

Como decide o que aplicar:
  1. Cada arquivo aplicado fica registrado em sys_migrations (criada aqui).
  2. Para bancos que já receberam migrações manuais, cada arquivo tem uma
     SONDAGEM (objeto sentinela criado por ele); se o objeto já existe, o
     arquivo é marcado como JA_EXISTENTE sem executar nada.
  3. Arquivos pendentes são executados na ordem numérica, em autocommit —
     cada .sql controla a própria transação (BEGIN/COMMIT internos) e alguns
     têm comandos pós-COMMIT (ANALYZE), que exigem autocommit.
"""

import argparse
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

# Consoles Windows (cp1252) não imprimem emoji; sem isto o runner morre no print.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

INIT_DB_DIR = Path(__file__).resolve().parent
ROOT_DIR = INIT_DB_DIR.parent
load_dotenv(ROOT_DIR / "CHAVES_DADOS.env", override=True)


def _sonda_coluna(tabela: str, coluna: str) -> str:
    return (
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        f"WHERE table_schema = 'public' AND table_name = '{tabela}' AND column_name = '{coluna}')"
    )


def _sonda_objeto(*nomes: str) -> str:
    """to_regclass cobre tabelas, views e índices (constraints UNIQUE criam índice homônimo)."""
    condicoes = " AND ".join(f"to_regclass('public.{nome}') IS NOT NULL" for nome in nomes)
    return f"SELECT {condicoes}"


# Sentinela por arquivo: o último/mais característico objeto que a migração
# cria. Se ele existe, a migração já foi aplicada manualmente no passado.
SONDAGENS = {
    "01_schema.sql": _sonda_objeto("dim_produtos", "sys_controle_sync"),
    "02_atualizacao_ia_avancada.sql": _sonda_coluna("dim_produtos", "nota_media_estrelas"),
    "03_migration_performance.sql": _sonda_objeto("idx_itens_model", "idx_pedidos_data"),
    "04_migration_global_metrics.sql": _sonda_objeto("fato_visao_geral_loja", "fato_metricas_produto_importadas"),
    "05_migration_ads_avancado.sql": _sonda_objeto("fato_ads_performance_produto"),
    "06_migration_topo_funil_organico.sql": _sonda_coluna("fato_trafego_diario", "impressoes"),
    "07_migration_trava_idempotencia.sql": _sonda_objeto("uk_trafego_item_data"),
    "08_migration_memoria_analitica.sql": _sonda_objeto("ia_execucoes_analiticas", "ia_snapshots_variacao", "ia_avaliacoes_acoes"),
    "09_migration_granularidade_importacao.sql": _sonda_coluna("fato_trafego_diario", "granularidade_origem"),
    "10_migration_cache_semantico_ia.sql": _sonda_coluna("ia_snapshots_variacao", "fingerprint_entrada"),
    "11_migration_checkpoint_execucao_ia.sql": _sonda_coluna("ia_execucoes_analiticas", "atualizado_em"),
    "12_migration_sync_lotes_e_views.sql": _sonda_objeto(
        "sys_lotes_importacao", "fato_historico_variacoes", "vw_funil_diario_item", "vw_vendas_diarias_variacao"
    ),
    "13_migration_indice_janelas_vendas.sql": _sonda_objeto("idx_pedidos_data_date"),
    "14_migration_indices_apoio_janelas.sql": _sonda_objeto("idx_historico_variacoes_data", "idx_metricas_importadas_data"),
    "15_migration_imagem_produto.sql": _sonda_coluna("dim_produtos", "imagem_url"),
    # A 16 altera o TIPO de uma coluna existente: a sondagem confere a escala.
    "16_migration_precisao_metricas.sql": (
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'fato_visao_geral_loja' "
        "AND column_name = 'metric_value' AND numeric_scale = 4)"
    ),
    "17_migration_pos_venda_e_promocoes.sql": _sonda_objeto("fato_promocoes_shopee", "fato_devolucoes"),
}


def conectar():
    """Conexão direta (fora do pool do app): sem statement_timeout, porque uma
    migração legítima pode passar de 30 segundos em bases grandes."""
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5433")),
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        connect_timeout=10,
        application_name="aplicar_migrations",
        # Mesmo fuso da sessão do app (utils/db_pool.py): datas de migrações e
        # sondagens enxergam o mesmo "hoje" que os workers.
        options=f"-c timezone={os.getenv('APP_TIMEZONE', 'America/Sao_Paulo')}",
    )
    conn.autocommit = True
    return conn


def garantir_tabela_controle(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sys_migrations (
            arquivo VARCHAR(255) PRIMARY KEY,
            modo VARCHAR(20) NOT NULL,           -- 'EXECUTADA' | 'JA_EXISTENTE'
            aplicado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """)


def listar_migrations() -> list[Path]:
    arquivos = sorted(
        p for p in INIT_DB_DIR.glob("*.sql")
        if p.name[:2].isdigit()
    )
    return arquivos


def registradas(cur) -> set[str]:
    cur.execute("SELECT arquivo FROM sys_migrations")
    return {linha[0] for linha in cur.fetchall()}


def sentinela_existe(cur, arquivo: str) -> bool:
    sonda = SONDAGENS.get(arquivo)
    if not sonda:
        return False
    cur.execute(sonda)
    return bool(cur.fetchone()[0])


def main() -> int:
    parser = argparse.ArgumentParser(description="Aplica as migrações pendentes do Data Warehouse.")
    parser.add_argument("--status", action="store_true", help="Somente mostra o estado; não aplica nada.")
    args = parser.parse_args()

    arquivos = listar_migrations()
    if not arquivos:
        print("Nenhum arquivo de migração encontrado em init_db/.")
        return 1

    try:
        conn = conectar()
    except Exception as exc:
        print(f"❌ Não foi possível conectar ao banco: {exc}")
        print("   Confira DB_HOST/DB_PORT/POSTGRES_* no CHAVES_DADOS.env e se o container está no ar.")
        return 1

    codigo_saida = 0
    try:
        cur = conn.cursor()
        garantir_tabela_controle(cur)
        aplicadas = registradas(cur)

        plano = []  # (arquivo, situacao)
        for caminho in arquivos:
            nome = caminho.name
            if nome in aplicadas:
                plano.append((caminho, "REGISTRADA"))
            elif sentinela_existe(cur, nome):
                plano.append((caminho, "JA_EXISTENTE"))
            else:
                plano.append((caminho, "PENDENTE"))

        largura = max(len(c.name) for c, _ in plano)
        print("\nEstado das migrações:")
        for caminho, situacao in plano:
            simbolo = {"REGISTRADA": "✅", "JA_EXISTENTE": "📌", "PENDENTE": "🕓"}[situacao]
            print(f"  {simbolo} {caminho.name.ljust(largura)}  {situacao}")

        pendentes = [c for c, s in plano if s == "PENDENTE"]
        ja_existentes = [c for c, s in plano if s == "JA_EXISTENTE"]

        if args.status:
            print(f"\n{len(pendentes)} pendente(s). Rode sem --status para aplicar.")
            return 0

        # Registra como JA_EXISTENTE o que foi aplicado manualmente no passado.
        for caminho in ja_existentes:
            cur.execute(
                "INSERT INTO sys_migrations (arquivo, modo) VALUES (%s, 'JA_EXISTENTE') ON CONFLICT (arquivo) DO NOTHING",
                (caminho.name,),
            )
        if ja_existentes:
            print(f"\n📌 {len(ja_existentes)} migração(ões) detectada(s) como já aplicadas manualmente e registradas.")

        if not pendentes:
            print("\n✅ Banco em dia: nenhuma migração pendente.")
            return 0

        print(f"\nAplicando {len(pendentes)} migração(ões) pendente(s)...")
        for caminho in pendentes:
            sql = caminho.read_text(encoding="utf-8")
            try:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO sys_migrations (arquivo, modo) VALUES (%s, 'EXECUTADA') ON CONFLICT (arquivo) DO NOTHING",
                    (caminho.name,),
                )
                print(f"  ✅ {caminho.name} aplicada.")
            except Exception as exc:
                print(f"  ❌ {caminho.name} FALHOU: {exc}")
                print("     A aplicação parou aqui; corrija o erro e rode novamente (as migrações são idempotentes).")
                codigo_saida = 1
                break

    finally:
        conn.close()

    if codigo_saida == 0:
        print("\n🎉 Concluído. O app já enxerga as mudanças (as sondagens têm cache de no máximo 5 minutos).")
    return codigo_saida


if __name__ == "__main__":
    sys.exit(main())
