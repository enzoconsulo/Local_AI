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

print("Smoke test do worker de importação OK")
