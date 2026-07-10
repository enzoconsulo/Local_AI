"""
pages/3___Cerebro_IA.py
========================
Conselho de Administração IA (CFO, CMO, COO) + Atuador Shopee.

Correções aplicadas nesta versão
---------------------------------
#7  memoria_ia — DISTINCT ON model_id (não mais item_id); salvar_log_acao
    agora grava o model_id, impedindo que ações de uma variação "contaminem"
    a memória de variações-irmãs do mesmo produto.
#8  validar_sugestao_ia() — camada de segurança em código Python que bloqueia
    sugestões fora da curva ANTES de exibir o botão de aprovação, sem depender
    do LLM "obedecer" o prompt.

Melhorias adicionais desta versão
----------------------------------
+   Pool de conexões via utils/db_pool (sem abrir/fechar por requisição).
+   calcular_score_urgencia() — prioriza produtos críticos no lote enviado à IA.
+   calcular_dias_estoque() — calcula autonomia de material ao ritmo atual.
+   gerar_alertas_criticos() — alertas determinísticos (sem LLM) para situações
    extremas: ROAS < 1×, material acabando em < 7 dias, lucro negativo.
+   Dashboard de KPIs agregados antes dos relatórios por produto.
+   Port corrigido para 8000 (alinhado com data_app.py e mesclar_llm.py).
+   tamanho_lote padrão elevado para 8 (menos chamadas RunPod, mais contexto).
+   Importação de criar_combo_shopee movida para o topo (evita ImportError tardio).
"""

import json
import os
import re
import sys
import litellm
import pandas as pd
import psycopg2.extras
import streamlit as st
from pathlib import Path
from dotenv import load_dotenv
import requests
from loguru import logger
import concurrent.futures

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

# override=True força o Python a usar a porta 5433 e ignora variáveis falsas do Windows
load_dotenv(ROOT_DIR / "CHAVES_DADOS.env", override=True)

from utils.shopee_core import (
    atualizar_preco_shopee,
    criar_promocao_shopee,
    criar_combo_shopee,
)
from utils.db_pool import get_connection

st.set_page_config(
    page_title="Cérebro Analítico & Atuador",
    page_icon="🧠",
    layout="wide",
)

# Porta 8000 — alinhada com data_app.py e o bootstrap llm.py
LITELLM_BASE = "http://localhost:8000/v1/chat/completions"

# Caminho para salvar a última auditoria no disco
CACHE_AUDITORIA = ROOT_DIR / "ultima_auditoria.json"

# Regras de execução recomendadas para o fluxo Shopee
ACTIONS_EXECUTAVEIS_SEGURAS = {"AUMENTAR_PRECO", "REDUZIR_PRECO", "CRIAR_PROMOCAO", "CRIAR_COMBO"}
ACTIONS_RECOMENDACAO_APENAS = {
    "PAUSAR_ADS",
    "AUMENTAR_BUDGET_ADS",
    "REDUZIR_BUDGET_ADS",
    "CRIAR_ADS",
    "EDITAR_ADS",
}


def classificar_modo_execucao(acao: str) -> tuple[str, str]:
    """Classifica se uma sugestão pode ser aplicada automaticamente ou apenas recomendada."""
    if acao in ACTIONS_EXECUTAVEIS_SEGURAS:
        return "EXECUTAR", "Ação operacional segura: o sistema pode aplicar após aprovação do usuário."
    if acao in ACTIONS_RECOMENDACAO_APENAS:
        return "RECOMENDAR", "Ação ligada a ads ou gasto: permanecerá como recomendação e revisão manual."
    return "RECOMENDAR", "Sem execução automática definida; siga o plano de ação recomendado."


# ==============================================================================
# SEÇÃO 1 — EXTRAÇÃO DO DATA WAREHOUSE
# ==============================================================================

def garantir_tabela_historico_variacoes():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS fato_historico_variacoes (
                    model_id BIGINT NOT NULL REFERENCES dim_variacoes(model_id) ON DELETE CASCADE,
                    data_registro DATE NOT NULL,
                    preco_venda_atual DECIMAL(10,2),
                    estoque_shopee INTEGER DEFAULT 0,
                    PRIMARY KEY (model_id, data_registro)
                );
                CREATE INDEX IF NOT EXISTS idx_fato_historico_variacoes_model_data
                ON fato_historico_variacoes (model_id, data_registro DESC);
            """)
        conn.commit()


def gerar_dossie_produtos_com_memoria():
    """
    Query principal do Cérebro IA.

    Correções aplicadas:
    - Fix #4, #7, #9, #11 e #12 mantidos rigorosamente.
    - Fix #13 (NOVO) Alinhamento de Lucro com JS: A projeção futura (previsao_lucro_7d)
              estava usando Preço Bruto - Custo, ignorando a taxa da Shopee nas vendas 
              futuras. Implementada a extração da taxa média real do produto e o cálculo 
              da 'margem_unitaria_real' para garantir que a IA veja a margem líquida exata,
              permitindo projeções de lucro negativo para que o CFO tome atitudes severas.
    """
    query = """
    WITH vendas_7d AS (
        SELECT
            i.model_id,
            SUM(i.quantidade) AS qtd_vendida,
            -- Se não tem repasse (escrow) porque o cliente ainda não confirmou, estimamos 82% do valor
            SUM(COALESCE(r.lucro_liquido_absoluto, (v.preco_venda_atual * 0.82) * i.quantidade)) AS lucro_liquido_total,
            AVG(COALESCE(r.comissao_shopee + r.taxa_servico + r.taxa_transacao, v.preco_venda_atual * 0.18)) AS taxa_media_shopee
        FROM fato_itens_pedido i
        JOIN fato_pedidos_venda p ON p.order_sn = i.order_sn
        JOIN dim_variacoes v ON v.model_id = i.model_id
        LEFT JOIN fato_repasse_escrow r ON i.order_sn = r.order_sn
        WHERE p.data_hora_criacao >= CURRENT_DATE - INTERVAL '7 days'
          AND p.status_pedido NOT IN ('CANCELLED', 'CANCELED', 'CANCELLED_BY_BUYER', 'IN_CANCEL')
        GROUP BY i.model_id
    ),
    vendas_anteriores AS (
        SELECT
            i.model_id,
            SUM(i.quantidade) AS qtd_vendida_antiga
        FROM fato_itens_pedido i
        JOIN fato_pedidos_venda p ON p.order_sn = i.order_sn
        WHERE p.data_hora_criacao >= CURRENT_DATE - INTERVAL '14 days'
          AND p.data_hora_criacao <  CURRENT_DATE - INTERVAL '7 days'
          AND p.status_pedido NOT IN ('CANCELLED', 'CANCELED', 'CANCELLED_BY_BUYER', 'IN_CANCEL')
        GROUP BY i.model_id
    ),
    ads_7d AS (
        SELECT
            item_id,
            SUM(impressoes)  AS impressoes,
            SUM(cliques)     AS cliques,
            SUM(custo_total) AS gasto_ads
        FROM fato_ads_palavras_chave
        WHERE data >= CURRENT_DATE - INTERVAL '7 days'
        GROUP BY item_id
    ),
    trafego_7d AS (
        SELECT
            item_id,
            SUM(visitantes_unicos) AS visitas,
            SUM(adicoes_carrinho)  AS carrinhos
        FROM fato_trafego_diario
        WHERE data >= CURRENT_DATE - INTERVAL '7 days'
        GROUP BY item_id
    ),
    variacoes_por_item AS (
        SELECT
            v.item_id,
            COUNT(*) AS qtd_variacoes
        FROM dim_variacoes v
        GROUP BY v.item_id
    ),
    pedidos_7d AS (
        SELECT
            i.model_id,
            COUNT(*) AS pedidos_7d
        FROM fato_itens_pedido i
        JOIN fato_pedidos_venda p ON i.order_sn = p.order_sn
        WHERE p.data_hora_criacao >= CURRENT_DATE - INTERVAL '7 days'
        GROUP BY i.model_id
    ),
    cancelamentos_7d AS (
        SELECT
            i.model_id,
            COUNT(*) FILTER (
                WHERE p.status_pedido IN ('CANCELLED', 'CANCELED', 'CANCELLED_BY_BUYER', 'IN_CANCEL')
            ) AS cancelamentos_7d
        FROM fato_itens_pedido i
        JOIN fato_pedidos_venda p ON i.order_sn = p.order_sn
        WHERE p.data_hora_criacao >= CURRENT_DATE - INTERVAL '7 days'
        GROUP BY i.model_id
    ),
    metricas_importadas_7d AS (
        SELECT
            item_id,
            SUM(CASE WHEN metric_name ILIKE 'venda%' OR metric_name ILIKE '%pedido%' OR metric_name ILIKE 'gmv%' OR metric_name ILIKE 'receita%' THEN metric_value ELSE 0 END) AS vendas_importadas_7d,
            SUM(CASE WHEN metric_name ILIKE 'receita%' OR metric_name ILIKE 'gmv%' THEN metric_value ELSE 0 END) AS receita_importada_7d,
            SUM(CASE WHEN metric_name ILIKE 'cancel%' THEN metric_value ELSE 0 END) AS cancelamentos_importados_7d,
            SUM(CASE WHEN metric_name ILIKE 'devol%' THEN metric_value ELSE 0 END) AS devolucoes_importadas_7d,
            SUM(CASE WHEN metric_name ILIKE 'reemb%' THEN metric_value ELSE 0 END) AS reembolsos_importados_7d,
            SUM(CASE WHEN metric_name ILIKE '%estoque%' OR metric_name ILIKE '%stock%' THEN metric_value ELSE 0 END) AS estoque_importado_7d,
            SUM(CASE WHEN metric_name ILIKE '%custo%' OR metric_name ILIKE '%gasto%' OR metric_name ILIKE 'ads%' THEN metric_value ELSE 0 END) AS custo_importado_7d
        FROM fato_metricas_produto_importadas
        WHERE data_registro >= CURRENT_DATE - INTERVAL '7 days'
        GROUP BY item_id
    ),
    macro_loja_7d AS (
        SELECT
            SUM(CASE WHEN metric_name ILIKE 'receita%' OR metric_name ILIKE 'gmv%' THEN metric_value ELSE 0 END) AS receita_macro_7d,
            AVG(CASE WHEN metric_name ILIKE 'convers%' THEN metric_value ELSE NULL END) AS conversao_macro_7d,
            AVG(CASE WHEN metric_name ILIKE 'roas%' THEN metric_value ELSE NULL END) AS roas_macro_7d,
            SUM(CASE WHEN metric_name ILIKE 'visita%' THEN metric_value ELSE 0 END) AS visitas_macro_7d,
            SUM(CASE WHEN metric_name ILIKE '%estoque%' OR metric_name ILIKE '%stock%' THEN metric_value ELSE 0 END) AS estoque_macro_7d
        FROM fato_visao_geral_loja
        WHERE data_registro >= CURRENT_DATE - INTERVAL '7 days'
    ),
    memoria_ia AS (
        SELECT DISTINCT ON (model_id)
            item_id, model_id, tipo_acao, detalhe_acao,
            impacto_projetado, data_aplicacao
        FROM log_acoes_shopee
        WHERE status_api = 'SUCESSO' AND model_id IS NOT NULL
        ORDER BY model_id, data_aplicacao DESC
    ),
    historico_variacoes AS (
        SELECT
            model_id,
            MAX(CASE WHEN data_registro = CURRENT_DATE THEN preco_venda_atual END) AS preco_hoje,
            MAX(CASE WHEN data_registro = CURRENT_DATE - INTERVAL '7 days' THEN preco_venda_atual END) AS preco_7d_atras,
            MAX(CASE WHEN data_registro = CURRENT_DATE THEN estoque_shopee END) AS estoque_hoje,
            MAX(CASE WHEN data_registro = CURRENT_DATE - INTERVAL '7 days' THEN estoque_shopee END) AS estoque_7d_atras
        FROM fato_historico_variacoes
        GROUP BY model_id
    )
    SELECT
        p.item_id,
        v.model_id,
        p.nome_atual,
        v.nome_variacao,
        v.preco_venda_atual,
        COALESCE(p.nota_media_estrelas, 0)   AS estrelas,
        COALESCE(p.likes_count, 0)           AS curtidas_favoritos,
        COALESCE(v.estoque_shopee, 0)        AS estoque_na_shopee,
        COALESCE(p.dias_pre_encomenda, 3)    AS tempo_preparo_dias,
        COALESCE(h.preco_hoje, v.preco_venda_atual) AS preco_hoje,
        COALESCE(h.preco_7d_atras, v.preco_venda_atual) AS preco_7d_atras,
        COALESCE(h.estoque_hoje, v.estoque_shopee, 0) AS estoque_hoje,
        COALESCE(h.estoque_7d_atras, v.estoque_shopee, 0) AS estoque_7d_atras,

        COALESCE(ven.qtd_vendida, 0)         AS vendas_7d,
        COALESCE(vant.qtd_vendida_antiga, 0) AS vendas_semana_passada,
        COALESCE(ven.taxa_media_shopee, 0)   AS taxa_shopee_unitaria,
        COALESCE(ven.lucro_liquido_total, 0) AS receita_liquida_7d,
        COALESCE(t.visitas, 0)               AS visitas_7d,
        COALESCE(t.carrinhos, 0)             AS carrinhos_7d,
        COALESCE(a.gasto_ads, 0)             AS gasto_ads_7d,
        COALESCE(vi.qtd_variacoes, 1)        AS qtd_variacoes_produto,
        COALESCE(ped.pedidos_7d, 0)          AS pedidos_7d,
        COALESCE(can.cancelamentos_7d, 0)    AS cancelamentos_7d,
        COALESCE(mi.vendas_importadas_7d, 0) AS vendas_importadas_7d,
        COALESCE(mi.receita_importada_7d, 0) AS receita_importada_7d,
        COALESCE(mi.cancelamentos_importados_7d, 0) AS cancelamentos_importados_7d,
        COALESCE(mi.devolucoes_importadas_7d, 0) AS devolucoes_importadas_7d,
        COALESCE(mi.reembolsos_importados_7d, 0) AS reembolsos_importados_7d,
        COALESCE(mi.estoque_importado_7d, 0) AS estoque_importado_7d,
        COALESCE(mi.custo_importado_7d, 0) AS custo_importado_7d,
        COALESCE(macro.receita_macro_7d, 0) AS receita_macro_7d,
        COALESCE(macro.conversao_macro_7d, 0) AS conversao_macro_7d,
        COALESCE(macro.roas_macro_7d, 0) AS roas_macro_7d,
        COALESCE(macro.visitas_macro_7d, 0) AS visitas_macro_7d,
        COALESCE(macro.estoque_macro_7d, 0) AS estoque_macro_7d,

        (
            (
                (CASE WHEN mat.unidade_medida = 'kg'
                      THEN (eng.peso_gramas / 1000.0)
                      ELSE eng.peso_gramas END
                 * mat.custo_por_unidade)
                + (eng.tempo_impressao_minutos * maq.custo_energia_hora / 60.0)
                + COALESCE(eng.custo_embalagem, 0)
            ) * (1 + (COALESCE(eng.taxa_perda_percentual, 0) / 100.0))
        )                                    AS custo_fabricacao_com_refugo,

        eng.peso_gramas,
        eng.taxa_perda_percentual,
        mat.nome                             AS nome_material,
        COALESCE(mat.estoque_atual, 0)       AS estoque_material_atual,
        mat.unidade_medida                   AS unidade_material,

        m.tipo_acao          AS ultima_acao,
        m.detalhe_acao       AS ultimo_detalhe,
        m.impacto_projetado  AS ultima_projecao

    FROM dim_produtos p
    JOIN dim_variacoes v              ON p.item_id   = v.item_id
    LEFT JOIN map_engenharia_produto eng ON v.model_id = eng.model_id
    LEFT JOIN dim_materiais mat       ON eng.id_material = mat.id_material
    LEFT JOIN dim_maquinas  maq       ON eng.id_maquina  = maq.id_maquina
    LEFT JOIN vendas_7d     ven       ON v.model_id  = ven.model_id
    LEFT JOIN vendas_anteriores vant  ON v.model_id  = vant.model_id
    LEFT JOIN ads_7d        a         ON p.item_id   = a.item_id
    LEFT JOIN trafego_7d    t         ON p.item_id   = t.item_id
    LEFT JOIN variacoes_por_item vi   ON p.item_id   = vi.item_id
    LEFT JOIN pedidos_7d    ped       ON v.model_id  = ped.model_id
    LEFT JOIN cancelamentos_7d can    ON v.model_id  = can.model_id
    LEFT JOIN metricas_importadas_7d mi ON p.item_id = mi.item_id
    LEFT JOIN macro_loja_7d macro     ON TRUE
    LEFT JOIN memoria_ia    m         ON v.model_id  = m.model_id
    LEFT JOIN historico_variacoes h   ON v.model_id  = h.model_id
    WHERE p.status_shopee = 'NORMAL';
    """

    garantir_tabela_historico_variacoes()

    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(query)
            registros = cur.fetchall()

    dossie = []
    for r in registros:
        preco        = float(r["preco_venda_atual"] or 0)
        preco_hoje   = float(r["preco_hoje"] or 0) or preco
        preco_7d     = float(r["preco_7d_atras"] or 0) or preco
        estoque_hoje = int(r["estoque_hoje"] or 0)
        estoque_7d   = int(r["estoque_7d_atras"] or 0)
        custo_fab    = float(r["custo_fabricacao_com_refugo"] or 0)
        receita_liq  = float(r["receita_liquida_7d"])

        # ====== ALINHAMENTO COM O SEU CÓDIGO JS ======
        # Extrai a taxa exata que a Shopee cobrou nas vendas desta semana.
        # Se for um produto novo/sem vendas, assume a taxa padrão base (18%).
        taxa_shopee_unitaria = float(r["taxa_shopee_unitaria"] or 0)
        if taxa_shopee_unitaria <= 0:
            taxa_shopee_unitaria = preco * 0.18
            
        # Margem real = Preço de Venda - Taxa Shopee - Custo de Fábrica
        margem_unitaria_real = preco - taxa_shopee_unitaria - custo_fab
        # =============================================

        qtd_variacoes = max(1, int(r["qtd_variacoes_produto"] or 1))
        gasto_ads    = float(r["gasto_ads_7d"]) / qtd_variacoes
        visitas      = int(r["visitas_7d"]) // qtd_variacoes
        carrinhos    = int(r["carrinhos_7d"]) // qtd_variacoes

        vendas       = int(r["vendas_7d"])
        vendas_antes = int(r["vendas_semana_passada"])
        pedidos_7d   = int(r["pedidos_7d"] or 0)
        cancelamentos_7d = int(r["cancelamentos_7d"] or 0)
        receita_importada_7d = float(r["receita_importada_7d"] or 0)
        custo_importado_7d = float(r["custo_importado_7d"] or 0)
        cancelamentos_importados_7d = int(r["cancelamentos_importados_7d"] or 0)
        estoque_importado_7d = float(r["estoque_importado_7d"] or 0)
        receita_macro_7d = float(r["receita_macro_7d"] or 0)
        conversao_macro_7d = float(r["conversao_macro_7d"] or 0)
        roas_macro_7d = float(r["roas_macro_7d"] or 0)
        visitas_macro_7d = float(r["visitas_macro_7d"] or 0)
        estoque_macro_7d = float(r["estoque_macro_7d"] or 0)

        lucro_operacional    = receita_liq - (custo_fab * vendas) - gasto_ads
        roas_atual           = round(receita_liq / gasto_ads, 2) if gasto_ads > 0 else 0
        taxa_conversao       = round(vendas / visitas * 100, 2) if visitas > 0 else 0
        taxa_abandono        = round((carrinhos - vendas) / carrinhos * 100, 2) if carrinhos > 0 else 0
        taxa_cancelamento_7d_perc = round(cancelamentos_7d / max(pedidos_7d, 1) * 100, 2) if pedidos_7d > 0 else 0
        preco_tendencia_perc = round(((preco_hoje - preco_7d) / preco_7d * 100), 2) if preco_7d > 0 else 0
        tendencia_perc       = (
            round((vendas - vendas_antes) / vendas_antes * 100, 2)
            if vendas_antes > 0 else (100 if vendas > 0 else 0)
        )

        capacidade_maxima = 999_999
        dias_estoque = 999

        historico_ia = None
        if r["ultima_acao"]:
            historico_ia = {
                "acao_passada": r["ultima_acao"],
                "detalhe":      r["ultimo_detalhe"],
                "projetado_na_epoca": r["ultima_projecao"],
            }

        dados_analiticos = {
            "item_id":   r["item_id"],
            "model_id":  r["model_id"],
            "nome_produto":      r["nome_atual"],
            "nome_variacao":     r["nome_variacao"],
            "preco_atual":       preco,
            "preco_hoje":        round(preco_hoje, 2),
            "preco_tendencia_7d_perc": preco_tendencia_perc,
            "estoque_shopee_hoje": estoque_hoje,
            "estoque_shopee_7d_atras": estoque_7d,
            "estoque_delta_7d_un": estoque_hoje - estoque_7d,
            "custo_fab_real":    round(custo_fab, 2),

            "vendas_7d_reais":              vendas,
            "tendencia_vendas_WoW_perc":    tendencia_perc,
            "taxa_abandono_carrinho_perc":  taxa_abandono,
            "lucro_liquido_real_7d":        round(lucro_operacional, 2),

            "REPUTACAO_estrelas":               float(r["estrelas"]),
            "REPUTACAO_curtidas_favoritos":     r["curtidas_favoritos"],
            
            "LOGISTICA_capacidade_material_restante": capacidade_maxima,
            "LOGISTICA_dias_estoque_restante":  dias_estoque,

            "TRAFEGO_visitas_7d":           visitas,
            "TRAFEGO_adicoes_carrinho_7d":  carrinhos,
            "TRAFEGO_taxa_conversao_perc":  taxa_conversao,

            "ADS_gasto_7d":   round(gasto_ads, 2),
            "ADS_roas_atual": roas_atual,
            "PEDIDOS_7d": pedidos_7d,
            "cancelamentos_7d": cancelamentos_7d,
            "taxa_cancelamento_7d_perc": taxa_cancelamento_7d_perc,
            "METRICAS_importadas_receita_7d": round(receita_importada_7d, 2),
            "METRICAS_importadas_custo_7d": round(custo_importado_7d, 2),
            "METRICAS_importadas_cancelamentos_7d": cancelamentos_importados_7d,
            "METRICAS_importadas_estoque_7d": round(estoque_importado_7d, 2),
            "LOJA_macro_receita_7d": round(receita_macro_7d, 2),
            "LOJA_macro_conversao_7d": round(conversao_macro_7d, 2),
            "LOJA_macro_roas_7d": round(roas_macro_7d, 2),
            "LOJA_macro_visitas_7d": round(visitas_macro_7d, 2),
            "LOJA_macro_estoque_7d": round(estoque_macro_7d, 2),
            "elasticidade_preco_volume": calcular_elasticidade_preco_volume(preco_hoje, preco_7d, vendas, vendas_antes),
            
            "previsao_vendas_7d": calcular_previsao_demanda_7d({
                "vendas_7d_reais": vendas,
                "tendencia_vendas_WoW_perc": tendencia_perc,
                "TRAFEGO_taxa_conversao_perc": taxa_conversao,
                "ADS_roas_atual": roas_atual,
                "LOGISTICA_dias_estoque_restante": dias_estoque,
                "LOGISTICA_capacidade_material_restante": capacidade_maxima,
                "estoque_shopee_hoje": estoque_hoje,
            }),
            
            # Aqui está a chave mestre: a projeção agora usa a Margem Unitária Real.
            # Removida a trava do 'max(0...)' ao redor de toda a conta para permitir que a IA veja
            # o prejuízo (lucro negativo) se o produto for ruim.
            "previsao_lucro_7d": round(
                (calcular_previsao_demanda_7d({
                    "vendas_7d_reais": vendas,
                    "tendencia_vendas_WoW_perc": tendencia_perc,
                    "TRAFEGO_taxa_conversao_perc": taxa_conversao,
                    "ADS_roas_atual": roas_atual,
                    "LOGISTICA_dias_estoque_restante": dias_estoque,
                    "LOGISTICA_capacidade_material_restante": capacidade_maxima,
                    "estoque_shopee_hoje": estoque_hoje,
                }) * margem_unitaria_real) - (gasto_ads * 0.9), 2
            ),
            
            "cluster_mercado": classificar_cluster({
                "lucro_liquido_real_7d": lucro_operacional,
                "ADS_roas_atual": roas_atual,
                "LOGISTICA_dias_estoque_restante": dias_estoque,
                "TRAFEGO_taxa_conversao_perc": taxa_conversao,
                "vendas_7d_reais": vendas,
            }),
            "recomendacao_executiva": gerar_recomendacao_executiva({
                "ADS_roas_atual": roas_atual,
                "taxa_cancelamento_7d_perc": taxa_cancelamento_7d_perc,
                "LOGISTICA_dias_estoque_restante": dias_estoque,
                "TRAFEGO_taxa_conversao_perc": taxa_conversao,
                "preco_tendencia_7d_perc": preco_tendencia_perc,
                "vendas_7d_reais": vendas,
                "ADS_gasto_7d": gasto_ads,
            }),
            "historico_acoes_passadas": historico_ia,
        }
        dossie.append(dados_analiticos)

    return dossie


# ==============================================================================
# SEÇÃO 2 — ANÁLISE PRÉVIA SEM LLM (regras determinísticas)
# ==============================================================================

def calcular_score_urgencia(d: dict) -> int:
    """
    Pontua a urgência de um produto de 0 a 100.
    Usado para ordenar o lote antes de enviar à IA — os casos mais críticos
    chegam primeiro e, se houver timeout de RunPod, ao menos foram analisados.
    """
    score = 0

    # Perdendo dinheiro em Ads (ROAS < 1 = gasta mais do que recebe)
    if d.get("ADS_gasto_7d", 0) > 5 and d.get("ADS_roas_atual", 0) < 1:
        score += 40

    # Material acabando em menos de 7 dias ao ritmo atual
    if d.get("LOGISTICA_dias_estoque_restante", 999) < 7:
        score += 35

    # Lucro operacional negativo
    if d.get("lucro_liquido_real_7d", 0) < 0:
        score += 30

    # Queda de vendas > 30 % semana a semana
    if d.get("tendencia_vendas_WoW_perc", 0) < -30:
        score += 25

    # Alta taxa de abandono + muitos favoritos = oportunidade de promoção perdida
    if d.get("taxa_abandono_carrinho_perc", 0) > 70 and d.get("REPUTACAO_curtidas_favoritos", 0) > 50:
        score += 20

    # Queda de preço forte em 7 dias e vendas baixas pode indicar perda de percepção
    if d.get("preco_tendencia_7d_perc", 0) < -15 and d.get("vendas_7d_reais", 0) <= 2:
        score += 10

    # Sem vendas com gasto em Ads
    if d.get("vendas_7d_reais", 0) == 0 and d.get("ADS_gasto_7d", 0) > 0:
        score += 30

    # Sinais extraídos de cancelamento e contexto macro importado
    if d.get("taxa_cancelamento_7d_perc", 0) > 12:
        score += 15

    if d.get("METRICAS_importadas_cancelamentos_7d", 0) > 0 and d.get("vendas_7d_reais", 0) <= 1:
        score += 10

    if d.get("LOJA_macro_conversao_7d", 0) > 0 and d.get("LOJA_macro_conversao_7d", 0) < 2 and d.get("ADS_gasto_7d", 0) > 5:
        score += 10

    return min(score, 100)


def calcular_dias_estoque(d: dict) -> int:
    """Retorna quantos dias de material restam ao ritmo de vendas atual."""
    return d.get("LOGISTICA_dias_estoque_restante", 999)


def calcular_elasticidade_preco_volume(preco_hoje: float, preco_7d: float, vendas_7d: int, vendas_antes: int) -> float:
    """Estimativa simples de sensibilidade de demanda a preço usando variação semanal."""
    if preco_7d <= 0 or vendas_antes <= 0:
        return 0.0
    delta_preco_pct = ((preco_hoje - preco_7d) / preco_7d) * 100
    delta_vendas_pct = ((vendas_7d - vendas_antes) / vendas_antes) * 100
    if abs(delta_preco_pct) < 0.5:
        return 0.0
    return round(delta_vendas_pct / delta_preco_pct, 3)


def calcular_previsao_demanda_7d(d: dict) -> int:
    """Previsão determinística de demanda para os próximos 7 dias."""
    vendas_7d = max(0, int(d.get("vendas_7d_reais", 0)))
    tendencia = float(d.get("tendencia_vendas_WoW_perc", 0))
    conversao = float(d.get("TRAFEGO_taxa_conversao_perc", 0))
    roas = float(d.get("ADS_roas_atual", 0))
    dias_estoque = int(d.get("LOGISTICA_dias_estoque_restante", 999))
    capacidade = int(d.get("LOGISTICA_capacidade_material_restante", 999_999))
    estoque = int(d.get("estoque_shopee_hoje", 0))

    forecast = vendas_7d * (1 + tendencia / 100)
    if conversao >= 3.0:
        forecast *= 1.10
    elif conversao <= 1.0:
        forecast *= 0.85
    if roas >= 3.0:
        forecast *= 1.05
    elif roas <= 1.0:
        forecast *= 0.90
    if dias_estoque < 14:
        forecast *= 0.85
    if estoque <= 0:
        forecast *= 0.60
    if capacidade > 0 and capacidade < 999_999:
        forecast = min(forecast, capacidade)
    return int(max(0, round(forecast)))


def gerar_recomendacao_executiva(d: dict) -> str:
    """Gera uma recomendação executiva curta e acionável."""
    if d.get("ADS_roas_atual", 0) < 1:
        return "Pausar ads e revisar preço até o ROAS voltar a ser saudável."
    if d.get("taxa_cancelamento_7d_perc", 0) > 10:
        return "Reduzir fricção de compra e revisar pós-venda para conter cancelamentos."
    if d.get("LOGISTICA_dias_estoque_restante", 999) < 7:
        return "Priorizar reabastecimento ou elevar preço para proteger margem."
    if d.get("TRAFEGO_taxa_conversao_perc", 0) < 2 and d.get("ADS_gasto_7d", 0) > 5:
        return "Reestruturar tráfego pago e criativos para recuperar conversão."
    if d.get("preco_tendencia_7d_perc", 0) < -10 and d.get("vendas_7d_reais", 0) <= 2:
        return "Reavaliar percepção de preço e testar novo posicionamento."
    return "Manter estratégia atual e monitorar os próximos 7 dias."


def classificar_cluster(d: dict) -> str:
    """Classifica o SKU em um cluster operacional simples."""
    if d.get("lucro_liquido_real_7d", 0) < 0 or d.get("ADS_roas_atual", 0) < 1:
        return "Em risco"
    if d.get("LOGISTICA_dias_estoque_restante", 999) < 14:
        return "Reabastecimento"
    if d.get("TRAFEGO_taxa_conversao_perc", 0) >= 3 and d.get("vendas_7d_reais", 0) > 0:
        return "Alto potencial"
    return "Estável"


def gerar_alertas_criticos(dossie: list[dict]) -> list[dict]:
    """
    Detecta situações que não precisam de LLM — são matematicamente óbvias.
    Retorna uma lista de alertas para exibir no topo do dashboard.
    """
    alertas = []
    for d in dossie:
        nome = f"{d['nome_produto']} ({d['nome_variacao']})"

        if d.get("ADS_gasto_7d", 0) > 5 and d.get("ADS_roas_atual", 0) < 1:
            alertas.append({
                "nivel": "🔴 CRÍTICO",
                "produto": nome,
                "mensagem": (
                    f"ROAS de {d['ADS_roas_atual']}× — cada R$ 1 em ads retorna "
                    f"menos de R$ 1. Pausar ou reduzir budget imediatamente."
                ),
            })

        dias = calcular_dias_estoque(d)
        if dias < 7:
            alertas.append({
                "nivel": "🟠 URGENTE",
                "produto": nome,
                "mensagem": (
                    f"Estoque de material suficiente para apenas {dias} dias "
                    f"ao ritmo atual de vendas. Reabastecer ou desacelerar vendas."
                ),
            })

        if d.get("lucro_liquido_real_7d", 0) < 0 and d.get("vendas_7d_reais", 0) > 0:
            alertas.append({
                "nivel": "🔴 CRÍTICO",
                "produto": nome,
                "mensagem": (
                    f"Lucro operacional de R$ {d['lucro_liquido_real_7d']:.2f} "
                    f"nos últimos 7 dias. Cada venda piora a situação."
                ),
            })

    return alertas


# ==============================================================================
# SEÇÃO 3 — MOTOR PREDITIVO (RUNPOD via LiteLLM Proxy)
# ==============================================================================

def validar_sugestao_ia(dados: dict, analise: dict) -> tuple[bool, str]:
    """
    Fix #8 — camada de segurança em código Python.
    Roda ANTES de exibir o botão de aprovação.
    Não depende do LLM obedecer o prompt.
    Retorna (True, "") se está ok, ou (False, motivo) se deve bloquear.
    """
    preco_atual      = dados.get("preco_atual", 0)
    capacidade_max   = dados.get("LOGISTICA_capacidade_material_restante", 999_999)
    novo_preco       = analise.get("novo_preco_sugerido", preco_atual)
    previsao_vendas  = analise.get("previsao_vendas_7d", 0)

    if novo_preco is None or novo_preco <= 0:
        return False, "Preço sugerido é inválido (zero, negativo ou ausente)."

    if preco_atual > 0:
        variacao = abs(novo_preco - preco_atual) / preco_atual
        if variacao > 0.80:
            return False, (
                f"Variação de {variacao * 100:.0f}% no preço excede o limite "
                f"de segurança de 80%. Ajuste manual necessário."
            )

    if previsao_vendas and capacidade_max < 999_999:
        if previsao_vendas > capacidade_max:
            return False, (
                f"Previsão de {previsao_vendas} un. excede a capacidade de "
                f"fábrica ({capacidade_max} un. de material restante)."
            )

    return True, ""


def acordar_modelo_ia():
    """Envia um ping simples para forçar o Cold Start do RunPod e aguarda até estar pronto."""
    payload = {
        "model": "cerebro-dados",
        "messages": [{"role": "user", "content": "Acorde. Responda apenas com a palavra 'OK'."}],
        "max_tokens": 5,
        "temperature": 0.1
    }
    try:
        logger.info("📡 [RUNPOD] Enviando ping de Wake-Up. Aguardando inicialização da GPU (pode levar 10 min)...")
        # Timeout alto (600s = 10 minutos) SOMENTE para esperar o RunPod alocar a GPU e baixar o modelo
        response = requests.post(LITELLM_BASE, json=payload, timeout=600)
        response.raise_for_status()
        logger.success("🟢 [RUNPOD] Servidor acordou e respondeu com sucesso! GPU Online.")
        return True
    except Exception as e:
        logger.error(f"🔴 [RUNPOD] Falha no Wake-Up: {e}")
        st.error(f"Falha ao acordar o modelo. Verifique os logs do RunPod. Erro: {e}")
        return False


def chamar_cerebro_runpod_preditivo(lote_json: list[dict], max_tentativas: int = 3) -> list[dict]:
    """
    Envia o lote ao modelo no RunPod via LiteLLM Proxy (porta 8000).
    Possui loop de tentativas (Retry) para garantir que a análise seja 100% feita pela IA.
    Timeout aumentado para 300s para suportar modelos gigantes (70B/72B).
    """
    import time  # Importação local para garantir que o sleep funcione

    prompt_sistema = """
    Você é o Conselho de Administração (CFO, CMO, COO) de uma Fazenda de Impressão 3D na Shopee.
    Realize uma Auditoria Profunda do Lote fornecido baseando-se em microeconomia.

    DIRETRIZES TÁTICAS:
    - COO: "LOGISTICA_capacidade_material_restante" é o teto de produção.
      NUNCA defina "previsao_vendas_7d" acima deste valor.
      Se "LOGISTICA_dias_estoque_restante" < 14, sugira AUMENTAR_PRECO
      para desacelerar vendas e preservar margem até o reabastecimento.
    - CMO: Use TRAFEGO_*, ADS_gasto_7d, ADS_roas_atual e LOJA_macro_* para avaliar saúde
      do tráfego pago e orgânico em relação ao comportamento da loja como um todo.
      • Use preco_tendencia_7d_perc, estoque_shopee_hoje e METRICAS_importadas_* para identificar
        sinais de desajuste de preço, risco de ruptura e mudança de demanda.
      • ROAS < 3× com gasto relevante → reduza preço OU pause ads antes de
        queimar mais orçamento em promoção.
      • Alta REPUTACAO_curtidas_favoritos + vendas baixas + tráfego saudável
        → CRIAR_PROMOCAO (notifica os interessados com push Shopee).
      • taxa_abandono_carrinho_perc > 65% → CRIAR_COMBO para diluir frete.
      • Se taxa_cancelamento_7d_perc > 10 ou cancelamentos_7d forem altos,
        priorize ações que reduzem fricção e reforcem confiança do cliente.
    - CFO: Maximize "lucro_liquido_real_7d" (já inclui ADS_gasto_7d no cálculo).
      Verifique se custo_fab_real * previsao_vendas_7d cabe dentro da margem.
      Use "elasticidade_preco_volume" para entender se o item reage fortemente a preço,
      e trate "cluster_mercado" como um sinal do estágio operacional do SKU.

    AÇÕES PERMITIDAS ("tipo_acao"):
    - "AUMENTAR_PRECO" ou "REDUZIR_PRECO"
    - "CRIAR_PROMOCAO"  (obrigatório o campo "horas_duracao_promocao")
    - "CRIAR_COMBO"
    - "MANTER"

    REGRA DE SEGURANÇA:
    - Priorize ações operacionais seguras: preço, promoção flash e combo.
    - Nunca sugira criação ou alteração de campanhas de ads pagas como ação executável.
      Se o problema for ads, descreva a recomendação na análise executiva e no plano de ação,
      mas não retorne um tipo_acao de ads como ação automática.

    FORMATO DE SAÍDA (RETORNE APENAS O ARRAY JSON, SEM MARKDOWN):
    [
      {
        "item_id": 123,
        "model_id": 456,
        "tipo_acao": "CRIAR_PROMOCAO",
        "novo_preco_sugerido": 45.90,
        "horas_duracao_promocao": 24,
        "previsao_vendas_7d": 80,
        "previsao_lucro_7d": 500.00,
        "elasticidade_preco_volume": -1.25,
        "cluster_mercado": "Alto potencial",
        "recomendacao_executiva": "Aumentar preço 5% se o estoque estiver saudável.",
        "relatorio_cfo_financas": "Margem absorve refugo; queima de 10% segura.",
        "relatorio_cmo_marketing": "ROAS 4.2× e conversão 3.1% saudáveis. 300 favoritos; push de 24h os notificará.",
        "relatorio_coo_operacoes": "Material para 150 peças. Fábrica aguenta.",
        "plano_acao_shopee": ["Ativar promoção relâmpago 24h para converter favoritos."],
        "analise_de_consequencias": "Pico esperado de 15 vendas nas próximas 24h."
      }
    ]
    """
    
    payload = {
        "model": "cerebro-dados",
        "messages": [
            {"role": "system", "content": prompt_sistema},
            {"role": "user",   "content": f"Auditoria:\n{json.dumps(lote_json, indent=2, ensure_ascii=False)}"},
        ],
        "max_tokens": 8000,
        "temperature": 0.2
    }

    # Loop de Resiliência: Tenta até 3 vezes antes de desistir
    for tentativa in range(1, max_tentativas + 1):
        try:
            logger.info(f"🧠 [RUNPOD] Processando lote de {len(lote_json)} produtos (Tentativa {tentativa}/{max_tentativas})...")
            
            # Timeout ajustado para 300 segundos (5 minutos)
            response = requests.post(LITELLM_BASE, json=payload, timeout=300)
            response.raise_for_status()

            texto = response.json()['choices'][0]['message']['content'].strip()
            
            # Limpeza robusta e segura
            texto = texto.replace("```json", "").replace("```", "").strip()

            match = re.search(r"\[.*\]", texto, re.DOTALL)
            if match:
                logger.success(f"✅ [RUNPOD] Lote processado com sucesso na tentativa {tentativa}!")
                return json.loads(match.group(0))
            
            logger.warning("⚠️ [RUNPOD] IA retornou um formato inesperado. Re-tentando...")
            
        except requests.exceptions.RequestException as e:
            logger.error(f"🔴 [RUNPOD] Falha de conexão/Timeout na tentativa {tentativa}: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"🔴 [RUNPOD] Falha ao decodificar JSON na tentativa {tentativa}: {e}")
        except Exception as e:
            logger.error(f"🔴 [RUNPOD] Erro inesperado na tentativa {tentativa}: {e}")
        
        # Se chegou aqui, falhou. Espera 5 segundos e tenta de novo.
        if tentativa < max_tentativas:
            logger.info("⏳ Aguardando 5 segundos antes de tentar novamente...")
            time.sleep(5)
            
    # Se sair do loop, todas as tentativas falharam. Trava o sistema.
    mensagem_critica = "🚨 FALHA CRÍTICA: A IA não conseguiu processar este lote após 3 tentativas. A operação foi abortada para garantir que nenhuma análise seja feita sem IA."
    logger.critical(mensagem_critica)
    st.error(mensagem_critica)
    st.stop()


def processar_em_lotes(dossie_completo: list[dict], tamanho_lote: int = 8) -> list[dict]:
    """
    Ordena o dossiê por urgência (maior score primeiro) e envia à IA em lotes usando
    concorrência (Threads) para explorar o Continuous Batching do vLLM e economizar no RunPod.
    """
    # Ordena por score de urgência (decrescente) antes de fatiar
    dossie_ordenado = sorted(
        dossie_completo,
        key=calcular_score_urgencia,
        reverse=True,
    )

    lotes = [
        dossie_ordenado[i : i + tamanho_lote]
        for i in range(0, len(dossie_ordenado), tamanho_lote)
    ]

    resultados_finais = []
    barra = st.progress(0, text="🚀 Iniciando auditoria paralela no RunPod...")
    lotes_concluidos = 0

    # Explorando a concorrência: Envia até 5 lotes simultaneamente para a GPU
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        # Mapeia cada futuro (tarefa) ao seu lote original
        futuros = {executor.submit(chamar_cerebro_runpod_preditivo, lote): lote for lote in lotes}

        for futuro in concurrent.futures.as_completed(futuros):
            lote_original = futuros[futuro]
            try:
                resultado_lote = futuro.result()
<<<<<<< HEAD

                # Faz o merge dos dados enriquecidos
                for rec in resultado_lote:
                    # Fix #10: blinda contra o LLM devolver item_id/model_id como
                    # string em vez de int — sem isso, o match falha e o produto
                    # some silenciosamente do relatório.
                    try:
                        rec_item_id = int(rec.get("item_id"))
                        rec_model_id = int(rec.get("model_id"))
                    except (TypeError, ValueError):
                        logger.warning(
                            f"⚠️ [RUNPOD] Registro com item_id/model_id inválido, ignorado: {rec}"
                        )
                        continue

                    original = next(
                        (d for d in lote_original
                         if int(d["item_id"]) == rec_item_id
                         and int(d["model_id"]) == rec_model_id),
                        None,
                    )
                    if original:
                        rec["item_id"] = rec_item_id
                        rec["model_id"] = rec_model_id
=======
                
                # Faz o merge dos dados enriquecidos
                for rec in resultado_lote:
                    original = next(
                        (d for d in lote_original
                         if d["item_id"] == rec.get("item_id")
                         and d["model_id"] == rec.get("model_id")),
                        None,
                    )
                    if original:
>>>>>>> 5ef92e814c0146ec7e0a8e6b0d4cf1d6d6348d4f
                        rec["dados_atuais"]     = original
                        rec["score_urgencia"]   = calcular_score_urgencia(original)
                        rec["dias_estoque"]     = calcular_dias_estoque(original)
                        rec.setdefault("previsao_vendas_7d", original.get("previsao_vendas_7d", 0))
                        rec.setdefault("previsao_lucro_7d", original.get("previsao_lucro_7d", 0))
                        rec.setdefault("elasticidade_preco_volume", original.get("elasticidade_preco_volume", 0))
                        rec.setdefault("cluster_mercado", original.get("cluster_mercado", "Estável"))
                        rec.setdefault("recomendacao_executiva", original.get("recomendacao_executiva", "Monitorar"))
<<<<<<< HEAD
                    else:
                        logger.warning(
                            f"⚠️ [RUNPOD] Nenhum produto original encontrado para "
                            f"item_id={rec_item_id}, model_id={rec_model_id} — descartado."
                        )
                        continue
                    resultados_finais.append(rec)
            except Exception as e:
                logger.error(f"Erro ao processar um dos lotes em paralelo: {e}")

=======
                    resultados_finais.append(rec)
            except Exception as e:
                logger.error(f"Erro ao processar um dos lotes em paralelo: {e}")
            
>>>>>>> 5ef92e814c0146ec7e0a8e6b0d4cf1d6d6348d4f
            # Atualiza a barra de progresso à medida que os lotes regressam da nuvem
            lotes_concluidos += 1
            barra.progress(
                lotes_concluidos / len(lotes),
                text=f"⏳ Conselho auditando lotes em paralelo ({lotes_concluidos}/{len(lotes)} concluídos)..."
            )

    barra.empty()
    return resultados_finais


# ==============================================================================
# SEÇÃO 4 — PERSISTÊNCIA
# ==============================================================================

def salvar_log_acao(
    item_id: int,
    model_id: int,         # Fix #7 — novo parâmetro
    tipo_acao: str,
    detalhe: str,
    impacto_json: dict,
    status: str,
):
    """Registra a decisão aprovada no Diário de Bordo (agora por variação)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO log_acoes_shopee
                    (item_id, model_id, tipo_acao, detalhe_acao, impacto_projetado, status_api)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (item_id, model_id, tipo_acao, detalhe, json.dumps(impacto_json), status),
            )
        conn.commit()


# ==============================================================================
# SEÇÃO 5 — INTERFACE DO USUÁRIO
# ==============================================================================

st.title("🧠 Conselho de Administração IA & Atuador")
st.markdown(
    "Auditoria profunda de **Finanças, Marketing e Fábrica** com predição de "
    "cenários e gatilhos de Notificação (Push) na Shopee."
)
st.info(
    "Fluxo recomendado: analisar → priorizar → aprovar. As ações de preço, promoção flash e combo podem ser aplicadas com aprovação; decisões de ads e orçamento permanecem em modo de recomendação e revisão manual."
)

# ─── Botão de disparo ────────────────────────────────────────────────────────
if st.button("⚡ Executar Auditoria Profunda (RunPod)", type="primary"):
    with st.status("Preparando o Conselho de IA...", expanded=True) as status_boot:
        
        st.write("📡 Enviando sinal de Wake-Up para o RunPod (pode levar 10min na 1ª vez)...")
        if not acordar_modelo_ia():
            status_boot.update(label="Falha ao iniciar o RunPod", state="error", expanded=True)
            st.stop() # Interrompe a execução se a IA não acordar

        st.write("📊 GPU online! Lendo Data Warehouse e calculando métricas...")
        dossie = gerar_dossie_produtos_com_memoria()

        if not dossie:
            st.warning(
                "Nenhum produto ativo encontrado. Execute a Sincronização primeiro."
            )
            st.stop()

        st.write(f"✅ {len(dossie)} variações carregadas. Iniciando auditoria...")
        resultados_ia = processar_em_lotes(dossie)
        st.session_state.analises_preditivas = resultados_ia
        
        # 💾 SALVA O BACKUP NO DISCO
        with open(CACHE_AUDITORIA, "w", encoding="utf-8") as f:
            json.dump(resultados_ia, f, ensure_ascii=False, indent=4)

        status_boot.update(label="Auditoria concluída e Salva com Sucesso!", state="complete", expanded=False)
    st.rerun()

st.divider()

# ─── Exibe resultados ─────────────────────────────────────────────────────────
if "analises_preditivas" not in st.session_state or not st.session_state.analises_preditivas:
    # 🔄 TENTA PUXAR O BACKUP DO DISCO
    if CACHE_AUDITORIA.exists():
        try:
            with open(CACHE_AUDITORIA, "r", encoding="utf-8") as f:
                st.session_state.analises_preditivas = json.load(f)
            st.success("📂 Última auditoria recuperada do backup local!")
        except Exception as e:
            st.session_state.analises_preditivas = []
    else:
        st.session_state.analises_preditivas = []

# Se mesmo com o backup ainda estiver vazio, aí sim pede para rodar
if not st.session_state.analises_preditivas:
    st.info("Clique no botão acima para iniciar a auditoria do Conselho de IA.")
    st.stop()

analises = st.session_state.analises_preditivas

# ── Dashboard de KPIs agregados ───────────────────────────────────────────────
st.subheader("📊 Visão Geral da Loja (últimos 7 dias)")

total_lucro    = sum(a.get("dados_atuais", {}).get("lucro_liquido_real_7d", 0) for a in analises)
total_vendas   = sum(a.get("dados_atuais", {}).get("vendas_7d_reais", 0) for a in analises)
total_gasto    = sum(a.get("dados_atuais", {}).get("ADS_gasto_7d", 0) for a in analises)
produtos_criticos = sum(1 for a in analises if a.get("score_urgencia", 0) >= 40)
dias_min_estoque  = min(
    (a.get("dias_estoque", 999) for a in analises if a.get("dias_estoque", 999) < 999),
    default=999,
)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("💰 Lucro Líquido Total", f"R$ {total_lucro:,.2f}")
c2.metric("📦 Vendas Totais", f"{total_vendas} un.")
c3.metric("📣 Gasto Total em Ads", f"R$ {total_gasto:,.2f}")
c4.metric(
    "🚨 Produtos Críticos",
    f"{produtos_criticos}",
    delta=f"de {len(analises)} analisados",
    delta_color="inverse",
)
c5.metric(
    "⏳ Menor Autonomia de Material",
    f"{dias_min_estoque if dias_min_estoque < 999 else '∞'} dias",
    delta_color="inverse" if dias_min_estoque < 14 else "normal",
)

# ── Alertas críticos (sem LLM) ────────────────────────────────────────────────
todos_os_dados = [a.get("dados_atuais", {}) for a in analises if a.get("dados_atuais")]
alertas = gerar_alertas_criticos(todos_os_dados)

if alertas:
    with st.expander(f"⚠️ {len(alertas)} alertas críticos detectados automaticamente", expanded=True):
        for alerta in alertas:
            st.error(f"**{alerta['nivel']} — {alerta['produto']}**\n\n{alerta['mensagem']}")

st.divider()

# ── Análises executivas adicionais ───────────────────────────────────────────
if analises:
    st.subheader("📈 Panorama Executivo")
    df_analises = pd.DataFrame(analises)
    if 'dados_atuais' in df_analises.columns:
        dados_expandidos = df_analises['dados_atuais'].apply(
            lambda x: pd.Series(x if isinstance(x, dict) else {})
        )
        df_analises = pd.concat(
            [df_analises.drop(columns=['dados_atuais']), dados_expandidos],
            axis=1,
        )

    if 'nome_produto' in df_analises.columns:
        df_analises['categoria'] = df_analises.get('nome_produto', '').astype(str).str.split().str[0]

    if not df_analises.empty:
        col1, col2, col3 = st.columns(3)
        
        # Recuperando colunas de forma segura (Se não existir, cria uma série com zero)
        score_urgencia = df_analises.get('score_urgencia', pd.Series([0]))
        taxa_cancel = df_analises.get('taxa_cancelamento_7d_perc', pd.Series([0]))
        lucro_liq = df_analises.get('lucro_liquido_real_7d', pd.Series([0]))

        with col1:
            st.metric("Produtos com urgência alta", int((score_urgencia >= 40).sum()))
        with col2:
            st.metric("Taxa média de cancelamento", f"{taxa_cancel.mean():.1f}%")
        with col3:
            st.metric("Margem média estimada", f"{lucro_liq.mean():.2f}")

        st.markdown("### 🧩 Agregações por categoria")
        if 'categoria' in df_analises.columns:
            agregacao_categoria = df_analises.groupby('categoria', dropna=False).agg(
                vendas=('vendas_7d_reais', 'sum'),
                lucro=('lucro_liquido_real_7d', 'sum'),
                gasto_ads=('ADS_gasto_7d', 'sum'),
                urgencia=('score_urgencia', 'mean'),
                cancelamento=('taxa_cancelamento_7d_perc', 'mean')
            ).sort_values(['lucro', 'vendas'], ascending=False)
            st.dataframe(agregacao_categoria.reset_index(), use_container_width=True)

        st.markdown("### 🎯 Ranking de potencial de margem")
        ranking = df_analises.copy()
        ranking['potencial_margem'] = (
            ranking.get('lucro_liquido_real_7d', 0) / (ranking.get('ADS_gasto_7d', 0) + 1)
            + ranking.get('vendas_7d_reais', 0) * 0.2
            - ranking.get('taxa_cancelamento_7d_perc', 0) * 0.5
        )
        ranking_top = ranking.sort_values('potencial_margem', ascending=False).head(10)
        if not ranking_top.empty:
            st.dataframe(ranking_top[['nome_produto','nome_variacao','vendas_7d_reais','lucro_liquido_real_7d','ADS_gasto_7d','potencial_margem']].reset_index(drop=True), use_container_width=True)

        st.markdown("### 🚨 Alertas automáticos")
        alertas_exec = []
        for _, row in df_analises.iterrows():
            nome = f"{row.get('nome_produto', 'Produto')} - {row.get('nome_variacao', '')}".strip()
            if row.get('TRAFEGO_taxa_conversao_perc', 0) < 2 and row.get('ADS_gasto_7d', 0) > 5:
                alertas_exec.append(("Queda de conversão", nome, "Conversão abaixo do limiar com gasto relevante em ads."))
            if row.get('taxa_cancelamento_7d_perc', 0) > 10:
                alertas_exec.append(("Alta taxa de cancelamento", nome, "Cancelamento acima de 10% no período recente."))
        if alertas_exec:
            for alerta in alertas_exec[:15]:
                st.warning(f"{alerta[0]} — {alerta[1]}: {alerta[2]}")
        else:
            st.info("Nenhum alerta automático detectado no momento.")

st.subheader("🧠 Elasticidade, Previsão e Recomendações")
if analises:
    tabela_exec = []
    for analise in analises:
        dados = analise.get("dados_atuais", {})
        if not dados:
            continue
        tabela_exec.append({
            "produto": dados.get("nome_produto", ""),
            "variação": dados.get("nome_variacao", ""),
            "elasticidade_preco_volume": analise.get("elasticidade_preco_volume", dados.get("elasticidade_preco_volume", 0)),
            "previsao_vendas_7d": analise.get("previsao_vendas_7d", dados.get("previsao_vendas_7d", 0)),
            "previsao_lucro_7d": analise.get("previsao_lucro_7d", dados.get("previsao_lucro_7d", 0)),
            "cluster": analise.get("cluster_mercado", dados.get("cluster_mercado", "Estável")),
            "recomendacao": analise.get("recomendacao_executiva", dados.get("recomendacao_executiva", "Monitorar")),
        })
    if tabela_exec:
        st.dataframe(pd.DataFrame(tabela_exec).sort_values(["previsao_lucro_7d", "previsao_vendas_7d"], ascending=False), use_container_width=True)

st.subheader("📋 Relatórios Executivos por Produto")

for analise in analises:
    dados = analise.get("dados_atuais", {})
    if not dados:
        continue

    acao          = analise.get("tipo_acao", "MANTER")
    score         = analise.get("score_urgencia", 0)
    dias_mat      = analise.get("dias_estoque", 999)
    preco_atual   = dados["preco_atual"]
    novo_preco    = analise.get("novo_preco_sugerido", preco_atual)

    icon_acao = {
        "AUMENTAR_PRECO":  "📈",
        "REDUZIR_PRECO":   "📉",
        "CRIAR_PROMOCAO":  "🔥",
        "CRIAR_COMBO":     "🛍️",
    }.get(acao, "⚖️")

    badge_urgencia = (
        "🔴 URGENTE" if score >= 40
        else "🟡 ATENÇÃO" if score >= 20
        else "🟢 OK"
    )
    dias_str = f"⏳ {dias_mat}d mat." if dias_mat < 999 else ""

    with st.expander(
        f"{icon_acao} {dados['nome_produto']} · {dados.get('nome_variacao', '')} "
        f"| {acao} | {badge_urgencia} {dias_str}"
    ):
        modo_execucao, detalhe_execucao = classificar_modo_execucao(acao)
        st.caption(f"🛡️ Modo de execução: **{modo_execucao}** — {detalhe_execucao}")

        # ── Abas do conselho ──────────────────────────────────────────────────
        st.markdown("### 🕵️ Auditoria do Conselho")
        tab_cfo, tab_cmo, tab_coo = st.tabs(
            ["💰 CFO (Finanças)", "🎯 CMO (Tráfego & Ads)", "🏭 COO (Operações)"]
        )

        with tab_cfo:
            st.info(analise.get("relatorio_cfo_financas", "Análise financeira não disponível."))
            custo = dados.get("custo_fab_real", 0)
            margem = ((preco_atual - custo) / preco_atual * 100) if preco_atual > 0 else 0
            st.caption(
                f"Custo de Fábrica (c/ refugo): **R$ {custo:.2f}** | "
                f"Margem Bruta: **{margem:.1f}%** | "
                f"Lucro Líquido 7d: **R$ {dados.get('lucro_liquido_real_7d', 0):.2f}**"
            )

        with tab_cmo:
            st.success(analise.get("relatorio_cmo_marketing", "Análise de marketing não disponível."))
            st.caption(
                f"⭐ {dados.get('REPUTACAO_estrelas', 0)} | "
                f"❤️ {dados.get('REPUTACAO_curtidas_favoritos', 0)} favoritos | "
                f"🛒 Abandono: {dados.get('taxa_abandono_carrinho_perc', 0):.1f}% | "
                f"📈 Conversão: {dados.get('TRAFEGO_taxa_conversao_perc', 0):.2f}% | "
                f"ROAS: {dados.get('ADS_roas_atual', 0):.1f}×"
            )

        with tab_coo:
            st.warning(analise.get("relatorio_coo_operacoes", "Análise operacional não disponível."))
            dias_label = f"{dias_mat} dias" if dias_mat < 999 else "estoque não mapeado"
            st.caption(
                f"🏭 Capacidade restante: **{dados.get('LOGISTICA_capacidade_material_restante', 0)} un.** "
                f"| Autonomia ao ritmo atual: **{dias_label}** "
                f"| Estoque Shopee: **{dados.get('estoque_na_shopee', 0)} un.**"
            )

        # ── Feedback Loop ─────────────────────────────────────────────────────
        hist = dados.get("historico_acoes_passadas")
        if hist:
            st.markdown("---")
            st.markdown("### 🔄 Feedback Loop (Aprendizado da IA)")
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown(f"**Ação anterior:** {hist.get('acao_passada', 'N/A')}")
                st.markdown(f"**Detalhe:** {hist.get('detalhe', '')}")
                st.markdown(f"**Projeção na época:** {hist.get('projetado_na_epoca', {})}")
            with col_b:
                st.markdown("**Realidade atual (7 dias):**")
                st.metric("Vendas reais", f"{dados.get('vendas_7d_reais', 0)} un.")
                st.metric("Lucro real", f"R$ {dados.get('lucro_liquido_real_7d', 0):.2f}")

        # ── Projeção de cenário ───────────────────────────────────────────────
        st.markdown("---")
        st.markdown("### 📊 Projeção de Cenário (Próximos 7 Dias)")

        c1, c2, c3 = st.columns(3)
        var_preco = ((novo_preco - preco_atual) / preco_atual * 100) if preco_atual > 0 else 0
        c1.metric(
            "Ajuste de Preço",
            f"R$ {preco_atual:.2f} → R$ {novo_preco:.2f}",
            f"{var_preco:+.1f}%",
        )

        vendas_atuais = dados["vendas_7d_reais"]
        vendas_proj   = analise.get("previsao_vendas_7d", vendas_atuais)
        delta_v = (
            f"+{vendas_proj} un." if vendas_atuais == 0
            else f"{(vendas_proj - vendas_atuais) / vendas_atuais * 100:+.1f}%"
        )
        c2.metric("Volume Projetado", f"{vendas_proj} un.", delta_v)

        lucro_atual = dados["lucro_liquido_real_7d"]
        lucro_proj  = analise.get("previsao_lucro_7d", lucro_atual)
        delta_l = (
            f"R$ {lucro_proj:.2f}" if lucro_atual == 0
            else f"{(lucro_proj - lucro_atual) / abs(lucro_atual) * 100:+.1f}%"
        )
        c3.metric("Lucro Projetado", f"R$ {lucro_proj:.2f}", delta_l)

        # ── Plano de ação ─────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("### 🚀 Plano de Ação Estratégico")
        for passo in (analise.get("plano_acao_shopee") or []):
            st.markdown(f"- {passo}")
        st.markdown(f"**🔮 Consequência:** {analise.get('analise_de_consequencias', '')}")

        # ── Botão Atuador com camada de segurança (Fix #8) ───────────────────
        if acao != "MANTER":
            valido, motivo = validar_sugestao_ia(dados, analise)

            if not valido:
                st.error(
                    f"🚫 Sugestão bloqueada pela camada de segurança:\n\n**{motivo}**\n\n"
                    "Edite manualmente os valores e aplique via pgAdmin se necessário."
                )
            elif modo_execucao == "RECOMENDAR":
                st.info(
                    "📌 Esta sugestão é estratégica e ficará em modo de recomendação. O sistema não executará campanhas de ads ou mudanças de orçamento automaticamente."
                )
            else:
                # Tudo validado — exibe o botão
                duracao = analise.get("horas_duracao_promocao", 24)

                if acao == "CRIAR_PROMOCAO":
                    texto_botao = f"🔥 Aprovar Promoção Flash: R$ {novo_preco:.2f} por {duracao}h"
                elif acao == "CRIAR_COMBO":
                    texto_botao = "🛍️ Aprovar Combo Promocional na Shopee"
                else:
                    texto_botao = f"✅ Aprovar Alteração: R$ {preco_atual:.2f} → R$ {novo_preco:.2f}"

                if st.button(
                    texto_botao,
                    key=f"btn_{dados['item_id']}_{dados['model_id']}",
                    use_container_width=True,
                ):
                    with st.spinner("Conectando aos satélites da Shopee..."):
                        sucesso, msg = False, "Ação em desenvolvimento."

                        if acao == "CRIAR_PROMOCAO":
                            sucesso, msg = criar_promocao_shopee(
                                dados["item_id"], dados["model_id"], novo_preco, duracao
                            )
                        elif acao in ("AUMENTAR_PRECO", "REDUZIR_PRECO"):
                            sucesso, msg = atualizar_preco_shopee(
                                dados["item_id"], dados["model_id"], novo_preco
                            )
                        elif acao == "CRIAR_COMBO":
                            sucesso, msg = criar_combo_shopee(
                                dados["item_id"], percentual_desconto=10
                            )

                        impacto_log = {
                            "vendas_projetadas": vendas_proj,
                            "lucro_projetado":   lucro_proj,
                            "estrategia":        acao,
                        }

                        # Fix #7 — grava model_id no log
                        if sucesso:
                            salvar_log_acao(
                                dados["item_id"],
                                dados["model_id"],
                                acao,
                                f"Aprovado com alvo R$ {novo_preco:.2f}",
                                impacto_log,
                                "SUCESSO",
                            )
                            st.success(msg)
                            if acao != "CRIAR_COMBO":
                                st.balloons()
                        else:
                            salvar_log_acao(
                                dados["item_id"],
                                dados["model_id"],
                                acao,
                                f"Falha — alvo R$ {novo_preco:.2f}",
                                impacto_log,
                                "ERRO_API",
                            )
                            st.error(f"Erro na API Shopee: {msg}")