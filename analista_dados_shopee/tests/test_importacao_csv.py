"""
Smoke test offline do módulo de importação de planilhas.

Não toca o banco: valida o contrato do módulo (funções extraídas da página 2
para workers/importar_planilhas.py) e as regras puras de parsing/rateio que
foram calibradas contra exports reais do Seller Center.
"""

import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from workers import importar_planilhas as ip

# Contrato do módulo (a página 2 importa estes nomes)
for fn in (
    "carregar_dataframe_limpo",
    "processar_arquivo_global",
    "processar_trafego_organico",
    "processar_relatorio_ads_avancado",
    "calcular_hash_arquivo",
    "lote_ja_importado",
    "registrar_lote_importacao",
    "buscar_importacoes_sobrepostas",
):
    assert hasattr(ip, fn), f"função ausente no worker: {fn}"

# limpar_valor: formatos BR e EN vistos nos exports reais
assert ip.limpar_valor("1.564,90") == 1564.90     # BR com milhar
assert ip.limpar_valor("1,234.56") == 1234.56     # EN com milhar
assert ip.limpar_valor("1,28%") == 1.28           # percentual BR
assert ip.limpar_valor("1.234") == 1234.0         # milhar BR sem decimal
assert ip.limpar_valor("12.5") == 12.5            # decimal EN simples
assert ip.limpar_valor("-") == 0.0                # ausência na Shopee
assert ip.limpar_valor_opcional("-") is None      # NULL preservado
assert ip.limpar_valor_opcional("0") == 0.0       # zero medido é zero

# Rateio sem perda: totais preservados
assert sum(ip.distribuir_inteiro(100, 7, d) for d in range(7)) == 100
assert float(sum(ip.distribuir_monetario(10.01, 3, d) for d in range(3))) == 10.01

# Métricas não-aditivas reconhecidas (taxas/médias nunca são somadas/rateadas)
for coluna in (
    "taxa de conversão de pedidos",
    "ctr",
    "vendas por pedido",
    "média de dias para recompra (pedido realizado)",
    "taxa de rejeição do produto",
):
    assert any(k in coluna for k in ip._METRICAS_DE_TAXA), f"não é taxa: {coluna}"
assert not any(k in "vendas (brl)" for k in ip._METRICAS_DE_TAXA)
assert not any(k in "unidades (pedido pago)" for k in ip._METRICAS_DE_TAXA)

# Datas: aceita date e datetime (página passa datetime; CLI passa date)
import datetime
assert ip._como_date(datetime.date(2026, 7, 13)) == datetime.date(2026, 7, 13)
assert ip._como_date(datetime.datetime(2026, 7, 13, 23, 59)) == datetime.date(2026, 7, 13)

# Nome de arquivo real com '+' e '%20' normalizado
assert "gmv max" in ip._nome_arquivo_normalizado("Shop+GMV+MAX-Detail-Data-05_07_2026.csv")
assert "ad group" in ip._nome_arquivo_normalizado("Shopee-Ads-Ad-Group-Data-05_07_2026.csv")

# ── limpar_valor: ambiguidade BR/EN resolvida ────────────────────────────────
# Milhar EN exige decimal explícito ou 2+ grupos; um grupo sem ponto é decimal BR.
assert ip.limpar_valor("3,333") == 3.333          # média BR com 3 casas (antes: 3333!)
assert ip.limpar_valor("0,123") == 0.123          # taxa BR (antes: 123!)
assert ip.limpar_valor("1,234,567") == 1234567.0  # milhar EN com 2+ grupos
assert ip.limpar_valor("12,345.67") == 12345.67   # milhar EN com decimal

# ── GMV Max: decisão de linha que impede dupla contagem e perda de gasto ────
# Validada contra exports reais de 05–11/07/2026: os MESMOS produtos aparecem
# no "Dados Gerais" (método GMV Max, despesa 0) e no arquivo Detail (despesa real).
assert ip._e_arquivo_gmv_max_detail("Shop+GMV+MAX-Detail-Data-05_07_2026-11_07_2026.csv")
assert not ip._e_arquivo_gmv_max_detail("Dados+Gerais+de+Anúncios+Shopee-05_07_2026-11_07_2026.csv")

# Arquivo Detail: produtos entram; a linha-total '-' é a soma deles (redundante)
assert ip.decidir_linha_gmv_max(True, True, False) == "IMPORTAR"
assert ip.decidir_linha_gmv_max(True, True, True) == "IGNORAR"
# Dados Gerais COM Detail no lote: toda linha GMV Max sai (Detail é canônico)
assert ip.decidir_linha_gmv_max(False, True, False) == "IGNORAR"
assert ip.decidir_linha_gmv_max(False, True, True) == "IGNORAR"
# Dados Gerais SEM Detail: só a linha-total entra (única com a despesa real)
assert ip.decidir_linha_gmv_max(False, False, True) == "IMPORTAR_NA_LOJA"
assert ip.decidir_linha_gmv_max(False, False, False) == "IGNORAR"

# ── Fallback por nome com limiar (nome curto/vazio não casa com nada) ───────
produtos = [
    (58203972915, "gancho para mochila e bolsa pesada - suporta até 20kg - organizador de closet"),
    (58205593350, "mini lixeira automotiva para porta objetos carro universal com tampa"),
    (0, "loja global (ads da loja)"),
]
assert ip._item_por_nome_anuncio(
    "gancho para mochila e bolsa pesada - suporta até 20kg - organizador de closet [3]", produtos
) == 58203972915
assert ip._item_por_nome_anuncio("", produtos) is None
assert ip._item_por_nome_anuncio("nan", produtos) is None
assert ip._item_por_nome_anuncio("-", produtos) is None
assert ip._item_por_nome_anuncio("shop gmv max", produtos) is None  # não inventa vínculo

# ── Alocação inteira por maior resto (dossiê): soma SEMPRE igual ao total ────
from cerebro.dossie import alocar_inteiro_por_peso

assert sum(alocar_inteiro_por_peso(100, [0.5, 0.3, 0.2])) == 100
assert sum(alocar_inteiro_por_peso(7, [1 / 3, 1 / 3, 1 / 3])) == 7
assert alocar_inteiro_por_peso(0, [0.6, 0.4]) == [0, 0]
assert alocar_inteiro_por_peso(5, []) == []
assert sum(alocar_inteiro_por_peso(1, [0.0, 0.0])) == 1   # pesos zerados → igualitário
for total, pesos in ((13, [0.61, 0.29, 0.10]), (2, [0.9, 0.1]), (999, [0.5, 0.5])):
    aloc = alocar_inteiro_por_peso(total, pesos)
    assert sum(aloc) == total and all(v >= 0 for v in aloc), (total, pesos, aloc)

# ── SQL somente-leitura: alias em português não é mais falso positivo ───────
from cerebro.consultor import validar_sql_somente_leitura

validar_sql_somente_leitura('SELECT 1 AS "vendas do mês"')  # não pode levantar
for sql_proibido in ("DO $$ BEGIN NULL; END $$", "SELECT 1; DROP TABLE x", "DELETE FROM dim_produtos"):
    try:
        validar_sql_somente_leitura(sql_proibido)
        raise AssertionError(f"SQL proibido aceito: {sql_proibido}")
    except ValueError:
        pass

# ── UF do destinatário (sync_pedidos) ────────────────────────────────────────
from workers.sync_pedidos import _uf_do_pedido

assert _uf_do_pedido({"recipient_address": {"state": "SP"}}) == "SP"
assert _uf_do_pedido({"recipient_address": {"state": "São Paulo"}}) == "SP"
assert _uf_do_pedido({"recipient_address": {"state": "rio grande do sul"}}) == "RS"
assert _uf_do_pedido({"recipient_address": {"state": ""}}) is None
assert _uf_do_pedido({"region": "BR"}) is None  # país nunca vira UF

print("Smoke test do worker de importação OK")
