"""
pages/3___Cerebro_IA.py
========================
Conselho de Administração IA (CFO, CMO, COO) + Atuador Shopee.
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
from datetime import datetime

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
    layout="wide"
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
    Contém a visão expandida de 30 dias, trava de insumos infinitos e filtro de fantasmas.
    Atualizada com regras reais de repasse MEI Shopee (20% + R$3).
    """
    query = """
    WITH vendas_7d AS (
        SELECT
            i.model_id,
            SUM(i.quantidade) AS qtd_vendida,
            SUM(COALESCE(r.lucro_liquido_absoluto, ((v.preco_venda_atual * 0.80) - 3.00) * i.quantidade)) AS lucro_liquido_total,
            AVG(COALESCE(r.comissao_shopee + r.taxa_servico + r.taxa_transacao, (v.preco_venda_atual * 0.20) + 3.00)) AS taxa_media_shopee
        FROM fato_itens_pedido i
        JOIN fato_pedidos_venda p ON p.order_sn = i.order_sn
        JOIN dim_variacoes v ON v.model_id = i.model_id
        LEFT JOIN fato_repasse_escrow r ON i.order_sn = r.order_sn
        WHERE p.data_hora_criacao >= CURRENT_DATE - INTERVAL '7 days'
          AND p.status_pedido NOT IN ('CANCELLED', 'CANCELED', 'CANCELLED_BY_BUYER', 'IN_CANCEL')
        GROUP BY i.model_id
    ),
    vendas_30d AS (
        SELECT
            i.model_id,
            SUM(i.quantidade) AS qtd_vendida_30d,
            SUM(COALESCE(r.lucro_liquido_absoluto, ((v.preco_venda_atual * 0.80) - 3.00) * i.quantidade)) AS receita_liquida_30d,
            AVG(COALESCE(r.comissao_shopee + r.taxa_servico + r.taxa_transacao, (v.preco_venda_atual * 0.20) + 3.00)) AS taxa_media_shopee_30d
        FROM fato_itens_pedido i
        JOIN fato_pedidos_venda p ON p.order_sn = i.order_sn
        JOIN dim_variacoes v ON v.model_id = i.model_id
        LEFT JOIN fato_repasse_escrow r ON i.order_sn = r.order_sn
        WHERE p.data_hora_criacao >= CURRENT_DATE - INTERVAL '30 days'
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
    ads_30d AS (
        SELECT
            item_id,
            SUM(custo_total) AS gasto_ads_30d
        FROM fato_ads_palavras_chave
        WHERE data >= CURRENT_DATE - INTERVAL '30 days'
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
    trafego_30d AS (
        SELECT
            item_id,
            SUM(visitantes_unicos) AS visitas_30d,
            SUM(adicoes_carrinho)  AS carrinhos_30d
        FROM fato_trafego_diario
        WHERE data >= CURRENT_DATE - INTERVAL '30 days'
        GROUP BY item_id
    ),
    variacoes_por_item AS (
        SELECT
            v.item_id,
            COUNT(*) AS qtd_variacoes
        FROM dim_variacoes v
        WHERE v.nome_variacao NOT ILIKE '%Excluída%' 
          AND v.nome_variacao NOT ILIKE '%Excluida%'
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
    pedidos_30d AS (
        SELECT i.model_id, COUNT(*) AS pedidos_30d
        FROM fato_itens_pedido i
        JOIN fato_pedidos_venda p ON i.order_sn = p.order_sn
        WHERE p.data_hora_criacao >= CURRENT_DATE - INTERVAL '30 days'
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
    cancelamentos_30d AS (
        SELECT
            i.model_id,
            COUNT(*) FILTER (
                WHERE p.status_pedido IN ('CANCELLED', 'CANCELED', 'CANCELLED_BY_BUYER', 'IN_CANCEL')
            ) AS cancelamentos_30d
        FROM fato_itens_pedido i
        JOIN fato_pedidos_venda p ON i.order_sn = p.order_sn
        WHERE p.data_hora_criacao >= CURRENT_DATE - INTERVAL '30 days'
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
            MAX(CASE WHEN data_registro = CURRENT_DATE - INTERVAL '30 days' THEN preco_venda_atual END) AS preco_30d_atras,
            MAX(CASE WHEN data_registro = CURRENT_DATE THEN estoque_shopee END) AS estoque_hoje,
            MAX(CASE WHEN data_registro = CURRENT_DATE - INTERVAL '7 days' THEN estoque_shopee END) AS estoque_7d_atras,
            MAX(CASE WHEN data_registro = CURRENT_DATE - INTERVAL '30 days' THEN estoque_shopee END) AS estoque_30d_atras
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
        COALESCE(h.preco_30d_atras, v.preco_venda_atual) AS preco_30d_atras,
        COALESCE(h.estoque_hoje, v.estoque_shopee, 0) AS estoque_hoje,
        COALESCE(h.estoque_7d_atras, v.estoque_shopee, 0) AS estoque_7d_atras,
        COALESCE(h.estoque_30d_atras, v.estoque_shopee, 0) AS estoque_30d_atras,

        COALESCE(ven.qtd_vendida, 0)         AS vendas_7d,
        COALESCE(v30.qtd_vendida_30d, 0)     AS vendas_30d,
        COALESCE(v30.receita_liquida_30d, 0) AS receita_liquida_30d,
        COALESCE(vant.qtd_vendida_antiga, 0) AS vendas_semana_passada,
        COALESCE(ven.taxa_media_shopee, 0)   AS taxa_shopee_unitaria,
        COALESCE(ven.lucro_liquido_total, 0) AS receita_liquida_7d,
        
        COALESCE(t.visitas, 0)               AS visitas_7d,
        COALESCE(t.carrinhos, 0)             AS carrinhos_7d,
        COALESCE(a.gasto_ads, 0)             AS gasto_ads_7d,
        
        COALESCE(t30.visitas_30d, 0)         AS visitas_30d,
        COALESCE(t30.carrinhos_30d, 0)       AS carrinhos_30d,
        COALESCE(a30.gasto_ads_30d, 0)       AS gasto_ads_30d,
        
        COALESCE(vi.qtd_variacoes, 1)        AS qtd_variacoes_produto,
        COALESCE(ped.pedidos_7d, 0)          AS pedidos_7d,
        COALESCE(can.cancelamentos_7d, 0)    AS cancelamentos_7d,
        COALESCE(ped30.pedidos_30d, 0)       AS pedidos_30d,
        COALESCE(can30.cancelamentos_30d, 0) AS cancelamentos_30d,
        
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
    LEFT JOIN vendas_30d    v30       ON v.model_id  = v30.model_id
    LEFT JOIN vendas_anteriores vant  ON v.model_id  = vant.model_id
    LEFT JOIN ads_7d        a         ON p.item_id   = a.item_id
    LEFT JOIN ads_30d       a30       ON p.item_id   = a30.item_id
    LEFT JOIN trafego_7d    t         ON p.item_id   = t.item_id
    LEFT JOIN trafego_30d   t30       ON p.item_id   = t30.item_id
    LEFT JOIN variacoes_por_item vi   ON p.item_id   = vi.item_id
    LEFT JOIN pedidos_7d    ped       ON v.model_id  = ped.model_id
    LEFT JOIN cancelamentos_7d can    ON v.model_id  = can.model_id
    LEFT JOIN pedidos_30d   ped30     ON v.model_id  = ped30.model_id
    LEFT JOIN cancelamentos_30d can30  ON v.model_id  = can30.model_id
    LEFT JOIN metricas_importadas_7d mi ON p.item_id = mi.item_id
    LEFT JOIN macro_loja_7d macro     ON TRUE
    LEFT JOIN memoria_ia    m         ON v.model_id  = m.model_id
    LEFT JOIN historico_variacoes h   ON v.model_id  = h.model_id
    WHERE p.status_shopee = 'NORMAL'
      AND v.nome_variacao NOT ILIKE '%Excluída%'
      AND v.nome_variacao NOT ILIKE '%Excluida%';
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
        preco_30d    = float(r["preco_30d_atras"] or 0) or preco
        estoque_hoje = int(r["estoque_hoje"] or 0)
        estoque_7d   = int(r["estoque_7d_atras"] or 0)
        estoque_30d  = int(r["estoque_30d_atras"] or 0)
        custo_fab    = float(r["custo_fabricacao_com_refugo"] or 0)
        receita_liq  = float(r["receita_liquida_7d"])
        receita_liq_30d = float(r["receita_liquida_30d"] or 0)

        taxa_shopee_unitaria = float(r["taxa_shopee_unitaria"] or 0)
        if taxa_shopee_unitaria <= 0:
            # FIX: Realidade MEI Shopee. Isso impede falsas margens gigantes!
            taxa_shopee_unitaria = (preco * 0.20) + 3.00
            
        margem_unitaria_real = preco - taxa_shopee_unitaria - custo_fab

        qtd_variacoes = max(1, int(r["qtd_variacoes_produto"] or 1))
        
        gasto_ads    = float(r["gasto_ads_7d"]) / qtd_variacoes
        visitas      = int(r["visitas_7d"]) // qtd_variacoes
        carrinhos    = int(r["carrinhos_7d"]) // qtd_variacoes
        gasto_ads_30d = float(r["gasto_ads_30d"] or 0) / qtd_variacoes
        visitas_30d = int(r["visitas_30d"] or 0) // qtd_variacoes
        carrinhos_30d = int(r["carrinhos_30d"] or 0) // qtd_variacoes

        vendas       = int(r["vendas_7d"])
        vendas_30d   = int(r["vendas_30d"] or 0)
        vendas_antes = int(r["vendas_semana_passada"])
        pedidos_7d   = int(r["pedidos_7d"] or 0)
        cancelamentos_7d = int(r["cancelamentos_7d"] or 0)
        pedidos_30d = int(r["pedidos_30d"] or 0)
        cancelamentos_30d = int(r["cancelamentos_30d"] or 0)
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
        lucro_operacional_30d = receita_liq_30d - (custo_fab * vendas_30d) - gasto_ads_30d
        roas_atual           = round(receita_liq / gasto_ads, 2) if gasto_ads > 0 else 0
        retorno_ads_30d      = round(receita_liq_30d / gasto_ads_30d, 2) if gasto_ads_30d > 0 else 0
        taxa_conversao       = round(vendas / visitas * 100, 2) if visitas > 0 else 0
        taxa_conversao_30d   = round(vendas_30d / visitas_30d * 100, 2) if visitas_30d > 0 else 0
        taxa_abandono        = round((carrinhos - vendas) / carrinhos * 100, 2) if carrinhos > 0 else 0
        taxa_abandono_30d    = round((carrinhos_30d - vendas_30d) / carrinhos_30d * 100, 2) if carrinhos_30d > 0 else 0
        taxa_cancelamento_7d_perc = round(cancelamentos_7d / max(pedidos_7d, 1) * 100, 2) if pedidos_7d > 0 else 0
        taxa_cancelamento_30d_perc = round(cancelamentos_30d / max(pedidos_30d, 1) * 100, 2) if pedidos_30d > 0 else 0
        preco_tendencia_perc = round(((preco_hoje - preco_7d) / preco_7d * 100), 2) if preco_7d > 0 else 0
        preco_tendencia_30d_perc = round(((preco_hoje - preco_30d) / preco_30d * 100), 2) if preco_30d > 0 else 0
        tendencia_perc       = (
            round((vendas - vendas_antes) / vendas_antes * 100, 2)
            if vendas_antes > 0 else (100 if vendas > 0 else 0)
        )

        capacidade_maxima = 999_999
        if r["peso_gramas"] and float(r["peso_gramas"]) > 0 and r["estoque_material_atual"] is not None:
            estoque_g = (
                float(r["estoque_material_atual"]) * 1000
                if r["unidade_material"] == "kg"
                else float(r["estoque_material_atual"])
            )
            if estoque_g > 0:
                capacidade_maxima = int(estoque_g / float(r["peso_gramas"]))

        if vendas > 0:
            taxa_diaria   = vendas / 7
            dias_estoque  = round(capacidade_maxima / taxa_diaria)
        else:
            dias_estoque  = 999

        taxa_diaria_30d = vendas_30d / 30
        dias_estoque_30d = round(capacidade_maxima / taxa_diaria_30d) if taxa_diaria_30d > 0 else 999
        ritmo_7d_vs_30d_perc = (
            round(((vendas / 7) / taxa_diaria_30d - 1) * 100, 2)
            if taxa_diaria_30d > 0 else 0
        )

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
            "qtd_variacoes_produto": qtd_variacoes,
            "nome_produto":      r["nome_atual"],
            "nome_variacao":     r["nome_variacao"],
            "preco_atual":       preco,
            "preco_hoje":        round(preco_hoje, 2),
            "preco_tendencia_7d_perc": preco_tendencia_perc,
            "preco_tendencia_30d_perc": preco_tendencia_30d_perc,
            "estoque_shopee_hoje": estoque_hoje,
            "estoque_shopee_7d_atras": estoque_7d,
            "estoque_shopee_30d_atras": estoque_30d,
            "estoque_delta_7d_un": estoque_hoje - estoque_7d,
            "estoque_delta_30d_un": estoque_hoje - estoque_30d,
            "custo_fab_real":    round(custo_fab, 2),

            "vendas_7d_reais":              vendas,
            "vendas_30d_reais":             vendas_30d,
            "tendencia_vendas_WoW_perc":    tendencia_perc,
            "ritmo_7d_vs_30d_perc":          ritmo_7d_vs_30d_perc,
            "taxa_abandono_carrinho_perc":  taxa_abandono,
            "lucro_liquido_real_7d":        round(lucro_operacional, 2),
            "lucro_liquido_real_30d":       round(lucro_operacional_30d, 2),
            "REPUTACAO_estrelas":               float(r["estrelas"]),
            "REPUTACAO_curtidas_favoritos":     r["curtidas_favoritos"],
            "LOGISTICA_capacidade_material_restante": capacidade_maxima,
            "LOGISTICA_dias_estoque_restante":  dias_estoque,
            "LOGISTICA_dias_estoque_base_30d":  dias_estoque_30d,
            "TRAFEGO_visitas_7d":           visitas,
            "TRAFEGO_adicoes_carrinho_7d":  carrinhos,
            "TRAFEGO_taxa_conversao_perc":  taxa_conversao,
            "TRAFEGO_visitas_30d":          visitas_30d,
            "TRAFEGO_adicoes_carrinho_30d": carrinhos_30d,
            "TRAFEGO_taxa_conversao_30d_perc": taxa_conversao_30d,
            "taxa_abandono_carrinho_30d_perc": taxa_abandono_30d,
            "ADS_gasto_7d":   round(gasto_ads, 2),
            "ADS_roas_atual": roas_atual,
            "ADS_gasto_30d": round(gasto_ads_30d, 2),
            "ADS_retorno_liquido_30d": retorno_ads_30d,
            "PEDIDOS_7d": pedidos_7d,
            "cancelamentos_7d": cancelamentos_7d,
            "taxa_cancelamento_7d_perc": taxa_cancelamento_7d_perc,
            "PEDIDOS_30d": pedidos_30d,
            "cancelamentos_30d": cancelamentos_30d,
            "taxa_cancelamento_30d_perc": taxa_cancelamento_30d_perc,
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
            
            # Chaves Macro para a IA e o Gatekeeper
            "vendas_30d_macro": int(r["vendas_30d"] or 0),
            "visitas_30d_macro": int(r["visitas_30d"] or 0),
            "carrinhos_30d_macro": int(r["carrinhos_30d"] or 0),
            "gasto_ads_30d_macro": float(r["gasto_ads_30d"] or 0),

            "previsao_vendas_7d": calcular_previsao_demanda_7d({
                "vendas_7d_reais": vendas,
                "vendas_30d_macro": int(r["vendas_30d"] or 0),
                "tendencia_vendas_WoW_perc": tendencia_perc,
                "TRAFEGO_taxa_conversao_perc": taxa_conversao,
                "ADS_roas_atual": roas_atual,
                "LOGISTICA_dias_estoque_restante": dias_estoque,
                "LOGISTICA_capacidade_material_restante": capacidade_maxima,
                "estoque_shopee_hoje": estoque_hoje,
            }),
            
            "previsao_lucro_7d": round(
                (calcular_previsao_demanda_7d({
                    "vendas_7d_reais": vendas,
                    "vendas_30d_macro": int(r["vendas_30d"] or 0),
                    "tendencia_vendas_WoW_perc": tendencia_perc,
                    "TRAFEGO_taxa_conversao_perc": taxa_conversao,
                    "ADS_roas_atual": roas_atual,
                    "LOGISTICA_dias_estoque_restante": dias_estoque,
                    "LOGISTICA_capacidade_material_restante": capacidade_maxima,
                    "estoque_shopee_hoje": estoque_hoje,
                }) * margem_unitaria_real) - (gasto_ads * 0.9), 2
            ),
            
            "previsao_vendas_30d": calcular_previsao_demanda_30d({
                "vendas_7d_reais": vendas,
                "vendas_30d_reais": vendas_30d,
                "TRAFEGO_taxa_conversao_perc": taxa_conversao,
                "TRAFEGO_taxa_conversao_30d_perc": taxa_conversao_30d,
                "LOGISTICA_capacidade_material_restante": capacidade_maxima,
            }),
            "previsao_lucro_30d": round(
                calcular_previsao_demanda_30d({
                    "vendas_7d_reais": vendas,
                    "vendas_30d_reais": vendas_30d,
                    "TRAFEGO_taxa_conversao_perc": taxa_conversao,
                    "TRAFEGO_taxa_conversao_30d_perc": taxa_conversao_30d,
                    "LOGISTICA_capacidade_material_restante": capacidade_maxima,
                }) * margem_unitaria_real - (gasto_ads_30d * 0.9), 2
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
    """
    score = 0

    if d.get("ADS_gasto_7d", 0) > 5 and d.get("ADS_roas_atual", 0) < 1:
        score += 40

    if d.get("LOGISTICA_dias_estoque_restante", 999) < 7:
        score += 35

    if d.get("lucro_liquido_real_7d", 0) < 0:
        score += 30

    if d.get("tendencia_vendas_WoW_perc", 0) < -30:
        score += 25

    if d.get("taxa_abandono_carrinho_perc", 0) > 70 and d.get("REPUTACAO_curtidas_favoritos", 0) > 50:
        score += 20

    if d.get("preco_tendencia_7d_perc", 0) < -15 and d.get("vendas_7d_reais", 0) <= 2:
        score += 10

    if d.get("vendas_7d_reais", 0) == 0 and d.get("ADS_gasto_7d", 0) > 0:
        score += 30

    if d.get("taxa_cancelamento_7d_perc", 0) > 12:
        score += 15

    if d.get("METRICAS_importadas_cancelamentos_7d", 0) > 0 and d.get("vendas_7d_reais", 0) <= 1:
        score += 10

    if d.get("LOJA_macro_conversao_7d", 0) > 0 and d.get("LOJA_macro_conversao_7d", 0) < 2 and d.get("ADS_gasto_7d", 0) > 5:
        score += 10

    return min(score, 100)


def calcular_dias_estoque(d: dict) -> int:
    return d.get("LOGISTICA_dias_estoque_restante", 999)


def calcular_elasticidade_preco_volume(preco_hoje: float, preco_7d: float, vendas_7d: int, vendas_antes: int) -> float:
    if preco_7d <= 0 or vendas_antes <= 0:
        return 0.0
    delta_preco_pct = ((preco_hoje - preco_7d) / preco_7d) * 100
    delta_vendas_pct = ((vendas_7d - vendas_antes) / vendas_antes) * 100
    if abs(delta_preco_pct) < 0.5:
        return 0.0
    return round(delta_vendas_pct / delta_preco_pct, 3)


def calcular_previsao_demanda_7d(d: dict) -> int:
    vendas_7d = max(0, int(d.get("vendas_7d_reais", 0)))
    vendas_30d = max(0, int(d.get("vendas_30d_macro", 0)))
    tendencia = float(d.get("tendencia_vendas_WoW_perc", 0))
    conversao = float(d.get("TRAFEGO_taxa_conversao_perc", 0))
    roas = float(d.get("ADS_roas_atual", 0))
    dias_estoque = int(d.get("LOGISTICA_dias_estoque_restante", 999))
    capacidade = int(d.get("LOGISTICA_capacidade_material_restante", 999_999))
    estoque = int(d.get("estoque_shopee_hoje", 0))

    # O sinal semanal reage rápido, mas é volátil. Com histórico de 30 dias,
    # ancoramos parte da estimativa na média semanal para reduzir ruído.
    forecast_semana = vendas_7d * (1 + tendencia / 100)
    media_semanal_30d = vendas_30d / 4.2857
    forecast = (0.65 * forecast_semana + 0.35 * media_semanal_30d) if vendas_30d > 0 else forecast_semana
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


def calcular_previsao_demanda_30d(d: dict) -> int:
    """Cenário mensal conservador, ancorado no realizado de 30 dias e limitado pela capacidade."""
    vendas_30d = max(0, int(d.get("vendas_30d_reais", d.get("vendas_30d_macro", 0)) or 0))
    vendas_7d = max(0, int(d.get("vendas_7d_reais", 0) or 0))
    capacidade = int(d.get("LOGISTICA_capacidade_material_restante", 999_999) or 999_999)
    conversao_7d = float(d.get("TRAFEGO_taxa_conversao_perc", 0) or 0)
    conversao_30d = float(d.get("TRAFEGO_taxa_conversao_30d_perc", 0) or 0)

    # Se não há histórico mensal, a extrapolação é deliberadamente simples e deve
    # aparecer como baixa evidência na interface, não como previsão de alta certeza.
    base = vendas_30d if vendas_30d > 0 else vendas_7d * (30 / 7)
    ritmo_recente = ((vendas_7d / 7) / (vendas_30d / 30) - 1) if vendas_30d > 0 else 0
    ajuste_ritmo = max(-0.25, min(0.25, ritmo_recente * 0.35))
    ajuste_conversao = 0.0
    if conversao_30d > 0:
        ajuste_conversao = max(-0.10, min(0.10, ((conversao_7d / conversao_30d) - 1) * 0.20))

    forecast = base * (1 + ajuste_ritmo + ajuste_conversao)
    if capacidade > 0 and capacidade < 999_999:
        forecast = min(forecast, capacidade)
    return int(max(0, round(forecast)))


def gerar_recomendacao_executiva(d: dict) -> str:
    # CORREÇÃO CRÍTICA: ROAS = 0 não significa ROAS ruim se o gasto em ADS também for 0.
    if d.get("ADS_gasto_7d", 0) > 0 and d.get("ADS_roas_atual", 0) < 1:
        return "Pausar ads imediatamente. Revisar palavras-chave e remover 'Seleção Automática'."
    if d.get("taxa_cancelamento_7d_perc", 0) > 10:
        return "Reduzir fricção de compra e revisar embalagem/comunicação para conter cancelamentos."
    if d.get("LOGISTICA_dias_estoque_restante", 999) < 7:
        return "Priorizar reabastecimento de filamento ou elevar preço para proteger a margem."
    if d.get("TRAFEGO_taxa_conversao_perc", 0) < 2 and d.get("ADS_gasto_7d", 0) > 5:
        return "Reestruturar tráfego pago (focar em correspondência exata) e revisar imagens de capa."
    if d.get("preco_tendencia_7d_perc", 0) < -10 and d.get("vendas_7d_reais", 0) <= 2:
        return "Reavaliar percepção de preço e focar na criação de Kits/Combos Promocionais."
    return "Manter estratégia atual e monitorar os próximos 7 dias."


def classificar_cluster(d: dict) -> str:
    # ROAS zero sem investimento não é um sinal de risco: não há campanha para avaliar.
    if d.get("lucro_liquido_real_7d", 0) < 0 or (
        d.get("ADS_gasto_7d", 0) > 0 and d.get("ADS_roas_atual", 0) < 1
    ):
        return "Em risco"
    if d.get("LOGISTICA_dias_estoque_restante", 999) < 14:
        return "Reabastecimento"
    if d.get("TRAFEGO_taxa_conversao_perc", 0) >= 3 and d.get("vendas_7d_reais", 0) > 0:
        return "Alto potencial"
    return "Estável"


def gerar_alertas_criticos(dossie: list[dict]) -> list[dict]:
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
    BLINDAGEM ANTI-NULL: Garante que mesmo se a IA devolver 'null', o sistema não quebra.
    """
    preco_atual      = float(dados.get("preco_atual") or 0)
    capacidade_max   = int(dados.get("LOGISTICA_capacidade_material_restante") or 999_999)
    
    np_raw           = analise.get("novo_preco_sugerido")
    novo_preco       = float(np_raw) if np_raw is not None else preco_atual
    
    pv_raw           = analise.get("previsao_vendas_7d")
    previsao_vendas  = int(pv_raw) if pv_raw is not None else 0

    if novo_preco is None or novo_preco <= 0:
        return False, "Preço sugerido é inválido (zero, negativo ou ausente)."

    if preco_atual > 0:
        variacao = abs(novo_preco - preco_atual) / preco_atual
        if variacao > 0.80:
            return False, (
                f"Variação de {variacao * 100:.0f}% no preço excede o limite "
                f"de segurança de 80%. Ajuste manual necessário."
            )

    if previsao_vendas > 0 and capacidade_max < 999_999:
        if previsao_vendas > capacidade_max:
            return False, (
                f"Previsão de {previsao_vendas} un. excede a capacidade de "
                f"fábrica ({capacidade_max} un. de material restante)."
            )

    return True, ""


def acordar_modelo_ia():
    payload = {
        "model": "cerebro-dados",
        "messages": [{"role": "user", "content": "Acorde. Responda apenas com a palavra 'OK'."}],
        "max_tokens": 5,
        "temperature": 0.1
    }
    try:
        logger.info("📡 [RUNPOD] Enviando ping de Wake-Up. Aguardando inicialização da GPU (pode levar 10 min)...")
        response = requests.post(LITELLM_BASE, json=payload, timeout=600)
        response.raise_for_status()
        logger.success("🟢 [RUNPOD] Servidor acordou e respondeu com sucesso! GPU Online.")
        return True
    except Exception as e:
        logger.error(f"🔴 [RUNPOD] Falha no Wake-Up: {e}")
        st.error(f"Falha ao acordar o modelo. Verifique os logs do RunPod. Erro: {e}")
        return False


def chamar_cerebro_runpod_preditivo(lote_json: list[dict], max_tentativas: int = 3) -> list[dict]:
    import time 

    prompt_sistema = """
    Você é o Conselho de Administração (CFO, CMO, COO) de uma operação profissional de E-commerce na Shopee especializada em IMPRESSÃO 3D SOB DEMANDA.
    Sua análise deve ser cirúrgica, matemática e adaptada exclusivamente a este modelo de negócios. Evite frases feitas e genéricas.

    REGRAS ABSOLUTAS DO MODELO DE NEGÓCIO (IMPRESSÃO 3D ON-DEMAND):
    1. ESTOQUE VIRTUAL (COO): Seu estoque é baseado em bobinas de filamento compartilhadas entre os produtos. Um anúncio sem vendas NÃO "imobiliza capital" e NÃO é "estoque encalhado". Nunca prescreva "queima de estoque" por baixa saída.
    2. CUSTO E MARGEM (CFO): Avalie rigorosamente o 'custo_fab_real' enviado nos dados. A taxa da Shopee para o vendedor gira em torno de 20% + R$ 3,00 fixos por pedido. Itens de ticket muito baixo têm suas margens destruídas por essa taxa fixa. Se a margem estiver apertada, sugira a "CRIAR_COMBO" (ex: Kits Leve 3) em vez de baixar o preço. NUNCA sugira um preço que resulte em prejuízo ou margem líquida inferior a 15%.
    3. MARKETING E ADS (CMO):
       - Se 'ADS_gasto_7d' ou 'gasto_ads_total_30d' for igual a 0.0, É ESTRITAMENTE PROIBIDO sugerir "pausar ads", "revisar orçamento" ou falar sobre ROAS. Se não há gasto, o problema é 100% tráfego orgânico e SEO.
       - Se houver gasto em Ads com ROAS ruim (< 2.0), recomende explicitamente pausar e recriar campanhas focando em "Busca por Correspondência Exata", alertando contra a "Seleção Automática de Palavras" da Shopee.
    4. SEGMENTAÇÃO DE PRODUTO (CRUCIAL PARA O PLANO DE AÇÃO):
       - PRODUTOS FUNCIONAIS (Ex: Suportes, Ganchos, Clipes, Organizadores, Porta Cuia): O cliente compra pela SOLUÇÃO do problema. O plano de ação deve focar em SEO profundo (palavras-chave no título) e competitividade de preço.
       - PRODUTOS DECORATIVOS/AESTHETIC (Ex: Porta Joias Coquette, Dragões, Estátuas): O cliente compra pela EMOÇÃO. O plano de ação deve focar em Discovery, fotos atraentes, ambientação realista na capa e criação de urgência visual.

    AÇÕES PERMITIDAS ("tipo_acao"):
    - "AUMENTAR_PRECO" ou "REDUZIR_PRECO" (somente se a elasticidade e a margem permitirem).
    - "CRIAR_PROMOCAO" (ótimo para gerar urgência e destravar carrinhos abandonados; exige definir "horas_duracao_promocao").
    - "CRIAR_COMBO" (estratégia primária para salvar margem de itens baratos).
    - "PAUSAR_ADS" (APENAS se ADS_gasto_7d > 0 e ROAS < 2.0).
    - "MANTER" (estratégia atual correta).

    ESTRUTURA DE DADOS QUE VOCÊ RECEBERÁ:
    - O lote contém PRODUTOS (item_id) com "metricas_macro_produto_30_dias".
    - Dentro de cada produto há "variacoes_ativas" contendo as métricas reais dos últimos 7 dias.

    FORMATO DE SAÍDA OBRIGATÓRIO:
    - Retorne APENAS um ÚNICO ARRAY JSON PLANO (sem tags markdown de bloco de código).
    - O array DEVE conter um objeto para CADA VARIAÇÃO (model_id) listada nos produtos do lote.
    
    Exemplo da estrutura esperada:
    [
      {
        "item_id": 123,
        "model_id": 456,
        "tipo_acao": "CRIAR_COMBO",
        "novo_preco_sugerido": 14.90,
        "horas_duracao_promocao": 0,
        "previsao_vendas_7d": 12,
        "previsao_lucro_7d": 55.50,
        "elasticidade_preco_volume": -0.5,
        "cluster_mercado": "Baixo Ticket - Necessita Kit",
        "recomendacao_executiva": "O preço atual de R$12,90 é muito sensível à taxa fixa de R$3 da Shopee. Criar combo de 3 unidades para diluir a taxa e aumentar o ROAS.",
        "relatorio_cfo_financas": "Margem líquida unitária comprometida pela taxa fixa. O combo eleva o ticket médio e recupera a rentabilidade por envio.",
        "relatorio_cmo_marketing": "Item funcional com boa busca, mas o cliente evita comprar apenas um devido ao frete. O combo resolve o atrito.",
        "relatorio_coo_operacoes": "Impressão rápida e filamento abundante, viável escalar via kits.",
        "plano_acao_shopee": ["1. Manter preço unitário.", "2. Criar combo leve 3 com 5% de desconto."],
        "analise_de_consequencias": "Crescimento imediato do Ticket Médio (AOV) e absorção saudável dos custos logísticos."
      }
    ]
    """
    
    payload = {
        "model": "cerebro-dados",
        "messages": [
            {"role": "system", "content": prompt_sistema},
            {"role": "user",   "content": f"Auditoria:\n{json.dumps(lote_json, indent=2, ensure_ascii=False)}"},
        ],
        "max_tokens": 8192,
        "temperature": 0.2
    }

    for tentativa in range(1, max_tentativas + 1):
        try:
            logger.info(f"🧠 [RUNPOD] Processando lote de {len(lote_json)} submódulos (Tentativa {tentativa}/{max_tentativas})...")
            
            response = requests.post(LITELLM_BASE, json=payload, timeout=300)
            response.raise_for_status()

            texto = response.json()['choices'][0]['message']['content'].strip()
            texto = texto.replace("```json", "").replace("```", "").strip()

            match = re.search(r"\[.*\]", texto, re.DOTALL)
            if match:
                logger.success(f"✅ [RUNPOD] Lote processado com sucesso na tentativa {tentativa}!")
                return json.loads(match.group(0))
            
            logger.warning("⚠️ [RUNPOD] IA retornou um formato inesperado. Re-tentando...")
            
        except requests.exceptions.Timeout as e:
            logger.error(f"🔴 [RUNPOD] Timeout na tentativa {tentativa}. O RunPod está sobrecarregado. Abortando este lote para não duplicar jobs: {e}")
            break
            
        except requests.exceptions.RequestException as e:
            logger.error(f"🔴 [RUNPOD] Falha de rede na tentativa {tentativa}: {e}")
            
        except json.JSONDecodeError as e:
            logger.error(f"🔴 [RUNPOD] IA retornou JSON inválido na tentativa {tentativa}: {e}")
            
        except Exception as e:
            logger.error(f"🔴 [RUNPOD] Erro inesperado na tentativa {tentativa}: {e}")
        
        if tentativa < max_tentativas:
            logger.info("⏳ Aguardando 5 segundos antes de tentar novamente...")
            time.sleep(5)
            
    mensagem_critica = "🚨 FALHA CRÍTICA: A IA não conseguiu processar este lote após 3 tentativas."
    logger.critical(mensagem_critica)
    st.error(mensagem_critica)
    st.stop()


def processar_em_lotes(dossie_completo: list[dict], max_vars_por_lote: int = 5) -> list[dict]:
    # 1. Agrupar Variações por Produto Pai
    produtos_agrupados = {}
    for var in dossie_completo:
        iid = var["item_id"]
        if iid not in produtos_agrupados:
            produtos_agrupados[iid] = {
                "item_id": iid,
                "nome_produto": var["nome_produto"],
                "score_urgencia_maximo": 0,
                "metricas_macro_produto_30_dias": {
                    "visitas_totais_30d": var.get("visitas_30d_macro", 0),
                    "adicoes_carrinho_totais_30d": var.get("carrinhos_30d_macro", 0),
                    "gasto_ads_total_30d": round(var.get("gasto_ads_30d_macro", 0), 2),
                    "estrelas": var.get("REPUTACAO_estrelas", 0),
                    "favoritos": var.get("REPUTACAO_curtidas_favoritos", 0)
                },
                "variacoes_ativas": []
            }
        
        score_var = calcular_score_urgencia(var)
        produtos_agrupados[iid]["score_urgencia_maximo"] = max(produtos_agrupados[iid]["score_urgencia_maximo"], score_var)
        
        produtos_agrupados[iid]["variacoes_ativas"].append({
            "model_id": var["model_id"],
            "nome_variacao": var["nome_variacao"],
            "preco_atual": var["preco_atual"],
            "custo_fabricacao_unitario": var.get("custo_fab_real", 0),
            "preco_tendencia_7d_perc": var.get("preco_tendencia_7d_perc", 0),
            "vendas_30d_reais": var["vendas_30d_macro"],
            "vendas_7d_reais": var["vendas_7d_reais"],
            "tendencia_vendas_WoW_perc": var.get("tendencia_vendas_WoW_perc", 0),
            "ritmo_7d_vs_30d_perc": var.get("ritmo_7d_vs_30d_perc", 0),
            "lucro_liquido_real_7d": var["lucro_liquido_real_7d"],
            "lucro_liquido_real_30d": var.get("lucro_liquido_real_30d", 0),
            "trafego_visitas_7d": var.get("TRAFEGO_visitas_7d", 0),
            "trafego_conversao_perc": var.get("TRAFEGO_taxa_conversao_perc", 0),
            "abandono_carrinho_perc": var.get("taxa_abandono_carrinho_perc", 0),
            "trafego_visitas_30d": var.get("TRAFEGO_visitas_30d", 0),
            "trafego_conversao_30d_perc": var.get("TRAFEGO_taxa_conversao_30d_perc", 0),
            "abandono_carrinho_30d_perc": var.get("taxa_abandono_carrinho_30d_perc", 0),
            "ads_gasto_7d": var.get("ADS_gasto_7d", 0),
            "retorno_liquido_por_ads": var.get("ADS_roas_atual", 0),
            "ads_gasto_30d": var.get("ADS_gasto_30d", 0),
            "retorno_liquido_por_ads_30d": var.get("ADS_retorno_liquido_30d", 0),
            "elasticidade_preco_volume": var.get("elasticidade_preco_volume", 0),
            "taxa_cancelamento_7d_perc": var["taxa_cancelamento_7d_perc"],
            "taxa_cancelamento_30d_perc": var.get("taxa_cancelamento_30d_perc", 0),
            "estoque_shopee_hoje": var["estoque_shopee_hoje"],
            "LOGISTICA_capacidade_material_restante": var["LOGISTICA_capacidade_material_restante"],
            "LOGISTICA_dias_estoque_restante": var["LOGISTICA_dias_estoque_restante"],
            "LOGISTICA_dias_estoque_base_30d": var.get("LOGISTICA_dias_estoque_base_30d", 999),
            "previsao_deterministica_vendas_7d": var.get("previsao_vendas_7d", 0),
            "previsao_deterministica_vendas_30d": var.get("previsao_vendas_30d", 0),
            "qualidade_evidencia": classificar_confianca_evidencia(var)[0],
            "limite_evidencia": classificar_confianca_evidencia(var)[1],
            "historico_acoes_passadas": var["historico_acoes_passadas"]
        })

    # 2. O GATEKEEPER: Separar os Vivos dos Fantasmas
    produtos_ativos = []
    resultados_finais = []
    
    for p in produtos_agrupados.values():
        macro = p["metricas_macro_produto_30_dias"]
        vendas_totais_30d = sum(v["vendas_30d_reais"] for v in p["variacoes_ativas"])
        
        if macro["visitas_totais_30d"] <= 10 and macro["gasto_ads_total_30d"] == 0 and vendas_totais_30d == 0:
            # Processamento GRATUITO e INSTANTÂNEO
            for var in p["variacoes_ativas"]:
                original = next((d for d in dossie_completo if d["item_id"] == p["item_id"] and d["model_id"] == var["model_id"]), None)
                if original:
                    rec_fantasma = {
                        "item_id": p["item_id"],
                        "model_id": var["model_id"],
                        "tipo_acao": "MANTER",
                        "novo_preco_sugerido": var["preco_atual"],
                        "previsao_vendas_7d": 0,
                        "previsao_lucro_7d": 0.0,
                        "elasticidade_preco_volume": 0.0,
                        "cluster_mercado": "Fantasma (Invisível)",
                        "recomendacao_executiva": "Produto sem tráfego orgânico. O problema é descoberta, não o preço.",
                        "relatorio_cfo_financas": "Sem custos variáveis, mas representa capital/esforço criativo parado.",
                        "relatorio_cmo_marketing": f"Apenas {macro['visitas_totais_30d']} visitas em 30 dias. O anúncio não está aparecendo nas buscas.",
                        "relatorio_coo_operacoes": "Operação ociosa para este SKU.",
                        "plano_acao_shopee": [
                            "1. TÍTULO: Reescreva incluindo palavras-chave exatas da busca.",
                            "2. FOTO: Troque a capa por uma imagem do item em uso.",
                            "3. IMPULSO: Inscreva em Campanhas Shopee gratuitas.",
                            "4. VALIDAÇÃO: Ative R$ 3,00 em 'Busca por Descoberta' só para testar impressões."
                        ],
                        "analise_de_consequencias": "Melhorar o SEO e a foto tirará o produto da invisibilidade para gerar os primeiros cliques.",
                        "dados_atuais": original,
                        "score_urgencia": 0,
                        "dias_estoque": calcular_dias_estoque(original)
                    }
                    resultados_finais.append(rec_fantasma)
        else:
            produtos_ativos.append(p)

    produtos_ativos = sorted(produtos_ativos, key=lambda x: x["score_urgencia_maximo"], reverse=True)

    # 3. SMART BATCHING: Fatiamento de Variações
    lotes = []
    for p in produtos_ativos:
        vars_ativas = p["variacoes_ativas"]
        for i in range(0, len(vars_ativas), max_vars_por_lote):
            chunk_vars = vars_ativas[i : i + max_vars_por_lote]
            p_chunk = {
                "item_id": p["item_id"],
                "nome_produto": p["nome_produto"],
                "metricas_macro_produto_30_dias": p["metricas_macro_produto_30_dias"],
                "variacoes_ativas": chunk_vars
            }
            lotes.append([p_chunk])

    if lotes:
        barra = st.progress(0, text="🚀 Iniciando auditoria C-Level (Smart Batching) no RunPod...")
        lotes_concluidos = 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futuros = {executor.submit(chamar_cerebro_runpod_preditivo, lote): lote for lote in lotes}

            for futuro in concurrent.futures.as_completed(futuros):
                try:
                    resultado_lote = futuro.result()

                    for rec in resultado_lote:
                        try:
                            rec_item_id = int(rec.get("item_id"))
                            rec_model_id = int(rec.get("model_id"))
                        except (TypeError, ValueError):
                            continue

                        original = next(
                            (d for d in dossie_completo
                             if int(d["item_id"]) == rec_item_id
                             and int(d["model_id"]) == rec_model_id),
                            None,
                        )
                        
                        if original:
                            rec["item_id"] = rec_item_id
                            rec["model_id"] = rec_model_id
                            rec["dados_atuais"]     = original
                            rec["score_urgencia"]   = calcular_score_urgencia(original)
                            rec["dias_estoque"]     = calcular_dias_estoque(original)
                            
                            # FALLBACK DE SEGURANÇA PARA PREVENIR TYPEERROR NONE
                            preco_original = float(original.get("preco_atual", 0))
                            novo_preco_sugerido = rec.get("novo_preco_sugerido")
                            if novo_preco_sugerido is None:
                                rec["novo_preco_sugerido"] = preco_original
                            
                            rec.setdefault("previsao_vendas_7d", original.get("previsao_vendas_7d", 0))
                            rec.setdefault("previsao_lucro_7d", original.get("previsao_lucro_7d", 0))
                            rec.setdefault("elasticidade_preco_volume", original.get("elasticidade_preco_volume", 0))
                            rec.setdefault("cluster_mercado", original.get("cluster_mercado", "Estável"))
                            rec.setdefault("recomendacao_executiva", original.get("recomendacao_executiva", "Monitorar"))
                            resultados_finais.append(rec)
                except Exception as e:
                    logger.error(f"Erro ao processar um dos lotes em paralelo: {e}")

                lotes_concluidos += 1
                barra.progress(
                    lotes_concluidos / len(lotes),
                    text=f"⏳ Conselho auditando {lotes_concluidos}/{len(lotes)} submódulos ativos..."
                )

        barra.empty()
        
    return resultados_finais


# ==============================================================================
# SEÇÃO 4 — PERSISTÊNCIA
# ==============================================================================

def salvar_log_acao(
    item_id: int,
    model_id: int,
    tipo_acao: str,
    detalhe: str,
    impacto_json: dict,
    status: str,
):
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
# SEÇÃO 5 — INTERFACE DO USUÁRIO (REFINADA COM PROFUNDIDADE ANALÍTICA)
# ==============================================================================

def processar_acao_api(acao: str, dados_var: dict, analise_var: dict, novo_preco: float):
    """Isola a chamada da API da Shopee para manter o front-end responsivo."""
    duracao = analise_var.get("horas_duracao_promocao", 24)
    sucesso, msg = False, "Erro Desconhecido"
    
    try:
        if acao == "CRIAR_PROMOCAO":
            sucesso, msg = criar_promocao_shopee(dados_var["item_id"], dados_var["model_id"], novo_preco, duracao)
        elif acao in ("AUMENTAR_PRECO", "REDUZIR_PRECO"):
            sucesso, msg = atualizar_preco_shopee(dados_var["item_id"], dados_var["model_id"], novo_preco)
        elif acao == "CRIAR_COMBO":
            sucesso, msg = criar_combo_shopee(dados_var["item_id"], percentual_desconto=10)
            
        impacto_log = {
            "vendas_projetadas": analise_var.get("previsao_vendas_7d", 0),
            "lucro_projetado": analise_var.get("previsao_lucro_7d", 0),
            "estrategia": acao
        }
        
        if sucesso:
            salvar_log_acao(dados_var["item_id"], dados_var["model_id"], acao, f"Aprovado (Alvo: R$ {novo_preco:.2f})", impacto_log, "SUCESSO")
            return True, msg
        else:
            salvar_log_acao(dados_var["item_id"], dados_var["model_id"], acao, f"Falha API (Alvo: R$ {novo_preco:.2f})", impacto_log, "ERRO_API")
            return False, f"Falha na API: {msg}"
    except Exception as e:
        logger.error(f"Erro ao processar API Shopee: {e}")
        return False, f"Erro interno: {e}"


def _serie_numerica(df: pd.DataFrame, coluna: str) -> pd.Series:
    """Retorna uma série numérica segura, inclusive para auditorias antigas no cache."""
    if coluna not in df.columns:
        return pd.Series(0.0, index=df.index, dtype="float64")
    return pd.to_numeric(df[coluna], errors="coerce").fillna(0.0)


def classificar_confianca_evidencia(dados: dict) -> tuple[str, str, str]:
    """Classifica a força da evidência; não confunde sinal curto com previsão validada."""
    vendas_30d = int(dados.get("vendas_30d_macro", 0) or 0)
    visitas_30d = int(dados.get("visitas_30d_macro", 0) or 0)
    vendas_7d = int(dados.get("vendas_7d_reais", 0) or 0)
    preco_mudou = abs(float(dados.get("preco_tendencia_7d_perc", 0) or 0)) >= 0.5

    if vendas_30d >= 20 and visitas_30d >= 100 and vendas_7d > 0:
        return "Alta", "Boa base de volume (30 dias)", "success"
    if vendas_30d >= 5 or visitas_30d >= 30:
        detalhe = "Amostra moderada; valide antes de escalar"
        if not preco_mudou:
            detalhe += ". Sem variação de preço suficiente para medir elasticidade"
        return "Moderada", detalhe, "warning"
    return "Baixa", "Amostra curta ou pouco tráfego; trate projeções como hipótese", "error"


def intervalo_demanda_exploratorio(dados: dict, previsao: float) -> tuple[int, int]:
    """Faixa transparente: combina a previsão com a média semanal de 30 dias e amplia sob pouca evidência."""
    base_30d = float(dados.get("vendas_30d_macro", 0) or 0) / 4.2857
    referencia = previsao if previsao > 0 else base_30d
    confianca, _, _ = classificar_confianca_evidencia(dados)
    amplitude = {"Alta": 0.20, "Moderada": 0.35, "Baixa": 0.60}[confianca]
    if referencia <= 0:
        return 0, 0
    return max(0, round(referencia * (1 - amplitude))), round(referencia * (1 + amplitude))


def rotulo_acao(acao: str) -> str:
    return {
        "MANTER": "Monitorar",
        "PAUSAR_ADS": "Pausar ads",
        "AUMENTAR_PRECO": "Aumentar preço",
        "REDUZIR_PRECO": "Reduzir preço",
        "CRIAR_PROMOCAO": "Criar promoção",
        "CRIAR_COMBO": "Criar combo",
    }.get(acao, str(acao).replace("_", " ").title())


def explicar_acao(acao: str) -> tuple[str, str]:
    """Texto de interface: deixa explícito o efeito e o próximo passo de cada recomendação."""
    explicacoes = {
        "AUMENTAR_PRECO": ("O preço publicado da variação será elevado para o valor proposto.", "Aplique somente se a margem e a evidência estiverem adequadas."),
        "REDUZIR_PRECO": ("O preço publicado da variação será reduzido para o valor proposto.", "Confira o impacto na margem antes de confirmar."),
        "CRIAR_PROMOCAO": ("Será criada uma promoção temporária com o preço proposto.", "O preço de tabela não é alterado permanentemente."),
        "CRIAR_COMBO": ("Será criado um combo com desconto padrão de 10% para o produto.", "O preço exibido é uma referência; confira a oferta criada no Seller Center."),
        "PAUSAR_ADS": ("Nenhuma alteração é enviada por esta tela.", "Pause ou ajuste a campanha manualmente no Seller Center."),
    }
    return explicacoes.get(acao, ("A recomendação não altera nada até sua confirmação.", "Leia o parecer e valide a ação manualmente."))

# ─── Estrutura Principal da Tela ──────────────────────────────────────────────
st.title("🧠 Conselho C-Level & Atuador IA")
st.markdown("Auditoria profunda de **Finanças, Marketing e Fábrica** com predição de cenários e gatilhos de Notificação (Push) na Shopee.")

# Inicialização e Cache
if "analises_preditivas" not in st.session_state:
    st.session_state.analises_preditivas = []
    if CACHE_AUDITORIA.exists():
        try:
            with open(CACHE_AUDITORIA, "r", encoding="utf-8") as f:
                st.session_state.analises_preditivas = json.load(f)
        except Exception:
            pass

# ─── Barra Lateral (Sidebar) para o Disparo ──────────────────────────────────
with st.container(border=True):
    st.subheader("Atualizar diagnóstico")
    st.caption("Esta ação lê o Data Warehouse, recalcula os indicadores e pede um novo parecer à IA. Ela não muda preços, anúncios ou campanhas.")
    st.info("Use o botão abaixo apenas quando quiser renovar a base e as recomendações. Os controles de leitura ficam logo a seguir.")
    
    if st.button("⚡ Executar Auditoria Profunda", type="primary", use_container_width=True):
        with st.status("Iniciando Conselho de IA...", expanded=True) as status_boot:
            st.write("📡 Acordando servidores (RunPod)...")
            if not acordar_modelo_ia():
                status_boot.update(label="Falha de Comunicação", state="error", expanded=True)
                st.stop() 
            
            st.write("📊 Lendo Data Warehouse e calculando métricas...")
            dossie = gerar_dossie_produtos_com_memoria()
            
            if not dossie:
                status_boot.update(label="Sem Produtos Ativos", state="error", expanded=True)
                st.stop()
                
            st.write(f"✅ {len(dossie)} variações enviadas para auditoria...")
            resultados_ia = processar_em_lotes(dossie)
            
            st.session_state.analises_preditivas = resultados_ia
            with open(CACHE_AUDITORIA, "w", encoding="utf-8") as f:
                json.dump(resultados_ia, f, ensure_ascii=False, indent=4)
                
            status_boot.update(label="Auditoria Concluída!", state="complete", expanded=False)
        st.rerun()

analises = st.session_state.analises_preditivas
if not analises:
    st.warning("Ainda não há uma auditoria carregada. Use “Executar Auditoria Profunda” acima para criar o primeiro diagnóstico.")
    st.stop()

# ─── Preparação do DataFrame Macro (Recuperado do seu código) ─────────────────
df_analises = pd.DataFrame(analises)
if 'dados_atuais' in df_analises.columns:
    dados_expandidos = df_analises['dados_atuais'].apply(lambda x: pd.Series(x if isinstance(x, dict) else {}))
    df_analises = pd.concat([df_analises.drop(columns=['dados_atuais']), dados_expandidos], axis=1)

# Campos de identificação também existem no resultado da IA e no dossiê expandido.
# Mantemos a versão do dossiê (a fonte observada) para filtros e cálculos consistentes.
df_analises = df_analises.loc[:, ~df_analises.columns.duplicated(keep='last')]

if 'nome_produto' in df_analises.columns:
    df_analises['categoria'] = df_analises.get('nome_produto', '').astype(str).str.split().str[0]

# A auditoria mistura fatos observados, inferências e texto do modelo. Estas colunas
# tornam a qualidade da base visível antes de qualquer decisão operacional.
for coluna in [
    'vendas_7d_reais', 'vendas_30d_macro', 'visitas_7d', 'visitas_30d_macro',
    'carrinhos_7d', 'ADS_gasto_7d', 'lucro_liquido_real_7d',
    'taxa_cancelamento_7d_perc', 'score_urgencia', 'dias_estoque',
    'preco_tendencia_7d_perc', 'elasticidade_preco_volume'
]:
    df_analises[coluna] = _serie_numerica(df_analises, coluna)

evidencias = df_analises.apply(
    lambda row: classificar_confianca_evidencia(row.to_dict()), axis=1
)
df_analises[['confianca', 'leitura_evidencia', 'tom_confianca']] = pd.DataFrame(
    evidencias.tolist(), index=df_analises.index
)

with st.container(border=True):
    st.subheader("Filtrar a leitura")
    st.caption("Os filtros alteram apenas o que você vê nesta página; não mudam a auditoria nem enviam alterações à Shopee.")
    opcoes_confianca = ["Alta", "Moderada", "Baixa"]
    filtro_evidencia, filtro_acao, filtro_busca = st.columns([3, 2, 3])
    with filtro_evidencia:
        confiancas_selecionadas = st.multiselect(
            "Força da evidência", opcoes_confianca, default=opcoes_confianca,
            help="Filtra pela qualidade do histórico disponível, não pela confiança do modelo de linguagem."
        )
    with filtro_acao:
        mostrar_apenas_acao = st.toggle("Mostrar só ações", value=False, help="Oculta SKUs cuja recomendação atual é apenas monitorar.")
    with filtro_busca:
        texto_busca = st.text_input("Buscar produto ou SKU", placeholder="Ex.: suporte, preto, 123456")

mascara = df_analises['confianca'].isin(confiancas_selecionadas)
if mostrar_apenas_acao and 'tipo_acao' in df_analises.columns:
    mascara &= df_analises['tipo_acao'].fillna('MANTER').ne('MANTER')
if texto_busca:
    busca = (df_analises.get('nome_produto', pd.Series('', index=df_analises.index)).astype(str)
             + ' ' + df_analises.get('nome_variacao', pd.Series('', index=df_analises.index)).astype(str))
    mascara &= busca.str.contains(texto_busca, case=False, na=False)

df_analises = df_analises.loc[mascara].copy()
ids_visiveis = set(df_analises.get('model_id', pd.Series(dtype='object')).astype(str))
analises = [a for a in analises if str(a.get('model_id', a.get('dados_atuais', {}).get('model_id', ''))) in ids_visiveis]

if df_analises.empty:
    st.info("Nenhum SKU corresponde aos filtros atuais. Ajuste os filtros na barra lateral.")
    st.stop()

st.markdown("""
<style>
    .stApp {font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;}
    .block-container {max-width: 1440px; padding-top: 2rem; padding-bottom: 3rem;}
    div[data-testid="stTabs"] button {font-size: .95rem; font-weight: 600; padding: .75rem 1rem;}
    div[data-testid="stTabs"] button[aria-selected="true"] {color: #5b8def;}
    div[data-testid="stButton"] > button {border-radius: 10px; min-height: 2.75rem; font-weight: 600;}
    div[data-testid="stExpander"] {border-radius: 12px; border-color: rgba(128, 145, 180, .35);}
    div[data-testid="stMetric"] {background: linear-gradient(135deg, #101b35, #16254a); border: 1px solid #2b4273; border-radius: 12px; padding: 14px;}
    div[data-testid="stMetricLabel"] {color: #b9c7e6;}
    div[data-testid="stMetricValue"] {color: #f7f9ff;}
    .ia-note {padding: .85rem 1rem; border-left: 4px solid #5b8def; background: #101b35; border-radius: 8px; margin: .4rem 0 1rem;}
    .ia-label {font-size: .78rem; letter-spacing: .04em; color: #aebee3; text-transform: uppercase;}
</style>
""", unsafe_allow_html=True)

# ─── Organização em 4 Abas Ergonômicas ────────────────────────────────────────
aba_dashboard, aba_atuador, aba_previsao, aba_dossies = st.tabs([
    "Resumo", 
    "Alterações recomendadas", 
    "Cenários e previsões", 
    "Pareceres e método"
])

# ==============================================================================
# ABA 1: VISÃO EXECUTIVA (KPIs, Categorias e Alertas)
# ==============================================================================
with aba_dashboard:
    st.markdown('<div class="ia-note"><span class="ia-label">Leitura responsável</span><br>Fatos observados (7 dias) são exibidos com contexto de 30 dias. A IA formula hipóteses de ação; a classificação de evidência indica quando executar, testar em pequena escala ou somente monitorar.</div>', unsafe_allow_html=True)
    total_lucro_visivel = _serie_numerica(df_analises, 'lucro_liquido_real_7d').sum()
    total_vendas_visivel = _serie_numerica(df_analises, 'vendas_7d_reais').sum()
    total_gasto_visivel = _serie_numerica(df_analises, 'ADS_gasto_7d').sum()
    total_visitas_visivel = _serie_numerica(df_analises, 'visitas_7d').sum()
    total_carrinhos_visivel = _serie_numerica(df_analises, 'carrinhos_7d').sum()
    total_pedidos_visivel = _serie_numerica(df_analises, 'PEDIDOS_7d').sum()
    total_cancelamentos_visivel = _serie_numerica(df_analises, 'cancelamentos_7d').sum()
    conversao_loja = (total_vendas_visivel / total_visitas_visivel * 100) if total_visitas_visivel else 0
    abandono_loja = ((total_carrinhos_visivel - total_vendas_visivel) / total_carrinhos_visivel * 100) if total_carrinhos_visivel else 0
    cancelamento_loja = (total_cancelamentos_visivel / total_pedidos_visivel * 100) if total_pedidos_visivel else 0
    retorno_ads = (total_lucro_visivel / total_gasto_visivel) if total_gasto_visivel else None
    evidencias_resumo = df_analises['confianca'].value_counts()
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Resultado operacional", f"R$ {total_lucro_visivel:,.2f}", help="Receita líquida registrada menos custo de fabricação e ads; não é lucro contábil completo.")
    k2.metric("Conversão ponderada", f"{conversao_loja:.2f}%" if total_visitas_visivel else "Sem dado", help="Unidades vendidas ÷ visitas. Evita a distorção de fazer média simples entre SKUs.")
    k3.metric("Retorno operacional / ads", "Sem ads" if retorno_ads is None else f"R$ {retorno_ads:.2f}", help="Resultado operacional dividido pelo gasto em ads. Não equivale a ROAS de receita bruta.")
    k4.metric("Cancelamento ponderado", f"{cancelamento_loja:.1f}%" if total_pedidos_visivel else "Sem dado")
    st.caption(f"Evidência dos {len(df_analises)} SKUs filtrados: {evidencias_resumo.get('Alta', 0)} alta, {evidencias_resumo.get('Moderada', 0)} moderada, {evidencias_resumo.get('Baixa', 0)} baixa. Abandono de carrinho observado: {abandono_loja:.1f}%" if total_carrinhos_visivel else f"Evidência dos {len(df_analises)} SKUs filtrados: {evidencias_resumo.get('Alta', 0)} alta, {evidencias_resumo.get('Moderada', 0)} moderada, {evidencias_resumo.get('Baixa', 0)} baixa.")
    st.divider()
    st.subheader("📊 Panorama Executivo (Últimos 7 dias)")
    
    total_lucro    = sum(a.get("dados_atuais", {}).get("lucro_liquido_real_7d", 0) for a in analises)
    total_vendas   = sum(a.get("dados_atuais", {}).get("vendas_7d_reais", 0) for a in analises)
    total_gasto    = sum(a.get("dados_atuais", {}).get("ADS_gasto_7d", 0) for a in analises)
    produtos_criticos = sum(1 for a in analises if a.get("score_urgencia", 0) >= 40)
    dias_min_estoque  = min((a.get("dias_estoque", 999) for a in analises if a.get("dias_estoque", 999) < 999), default=999)

    with st.container(border=True):
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("💰 Lucro Líquido", f"R$ {total_lucro:,.2f}")
        c2.metric("📦 Vendas Totais", f"{total_vendas} un.")
        c3.metric("📣 Gasto em Ads", f"R$ {total_gasto:,.2f}")
        c4.metric("🚨 Produtos Críticos", f"{produtos_criticos}", delta=f"de {len(analises)} avaliados", delta_color="inverse")
        c5.metric("⏳ Autonomia Mínima", f"{dias_min_estoque if dias_min_estoque < 999 else '∞'} dias", delta_color="inverse" if dias_min_estoque < 14 else "normal")

    st.divider()
    
    # Médias Macro
    score_urgencia = df_analises.get('score_urgencia', pd.Series([0]))
    taxa_cancel = df_analises.get('taxa_cancelamento_7d_perc', pd.Series([0]))
    lucro_liq = df_analises.get('lucro_liquido_real_7d', pd.Series([0]))
    
    c_m1, c_m2, c_m3 = st.columns(3)
    c_m1.metric("Itens com Urgência Alta", int((score_urgencia >= 40).sum()))
    c_m2.metric("Taxa Média de Cancelamento", f"{taxa_cancel.mean():.1f}%")
    c_m3.metric("Margem Média Estimada", f"R$ {lucro_liq.mean():.2f}")

    st.markdown("### Fila priorizada de decisão")
    fila_decisao = df_analises.copy()
    fila_decisao['ação'] = fila_decisao.get('tipo_acao', pd.Series('MANTER', index=fila_decisao.index)).fillna('MANTER').map(rotulo_acao)
    fila_decisao['faixa_demanda_7d'] = fila_decisao.apply(
        lambda row: "{}–{} un.".format(*intervalo_demanda_exploratorio(
            row.to_dict(), float(row.get('previsao_vendas_7d', 0) or 0)
        )), axis=1
    )
    fila_decisao['elasticidade_legivel'] = fila_decisao.apply(
        lambda row: f"{float(row.get('elasticidade_preco_volume', 0)):.2f}" if abs(float(row.get('preco_tendencia_7d_perc', 0))) >= 0.5 and float(row.get('vendas_30d_macro', 0)) >= 5 else "Não identificável",
        axis=1
    )
    fila_decisao = fila_decisao.sort_values(['score_urgencia', 'lucro_liquido_real_7d'], ascending=[False, True])
    colunas_fila = ['nome_produto', 'nome_variacao', 'ação', 'confianca', 'score_urgencia', 'lucro_liquido_real_7d', 'faixa_demanda_7d', 'elasticidade_legivel', 'leitura_evidencia']
    st.dataframe(
        fila_decisao[colunas_fila], use_container_width=True, hide_index=True, height=280,
        column_config={
            'nome_produto': 'Produto', 'nome_variacao': 'SKU', 'ação': 'Próxima ação',
            'confianca': 'Evidência', 'score_urgencia': st.column_config.ProgressColumn('Prioridade', min_value=0, max_value=100, format='%d/100'),
            'lucro_liquido_real_7d': st.column_config.NumberColumn('Resultado 7d', format='R$ %.2f'),
            'faixa_demanda_7d': 'Faixa exploratória (7d)', 'elasticidade_legivel': 'Elasticidade',
            'leitura_evidencia': 'Limite da leitura'
        }
    )
    st.caption("A faixa exploratória não é um intervalo estatístico: ela amplia a incerteza quando o histórico é escasso. Elasticidade só é mostrada quando houve variação material de preço e volume mínimo de dados.")

    col_agregacao, col_alertas = st.columns([6, 4])
    
    with col_agregacao:
        st.markdown("### 🧩 Agregações por Categoria")
        if 'categoria' in df_analises.columns:
            agregacao_categoria = df_analises.groupby('categoria', dropna=False).agg(
                vendas=('vendas_7d_reais', 'sum'),
                lucro=('lucro_liquido_real_7d', 'sum'),
                gasto_ads=('ADS_gasto_7d', 'sum'),
                urgencia=('score_urgencia', 'mean'),
                cancelamento=('taxa_cancelamento_7d_perc', 'mean')
            ).sort_values(['lucro', 'vendas'], ascending=False)
            
            st.dataframe(agregacao_categoria.reset_index(), use_container_width=True, hide_index=True)

    with col_alertas:
        st.markdown("### 🚨 Alertas Automáticos")
        # Alertas críticos de regra de negócio
        alertas_fortes = gerar_alertas_criticos([a.get("dados_atuais", {}) for a in analises if a.get("dados_atuais")])
        if alertas_fortes:
            for alerta in alertas_fortes:
                st.error(f"**{alerta['produto']}**: {alerta['mensagem']}", icon="🔴")
                
        # Alertas operacionais
        alertas_exec = []
        for _, row in df_analises.iterrows():
            nome = f"{row.get('nome_produto', 'Produto')} - {row.get('nome_variacao', '')}".strip()
            if row.get('TRAFEGO_taxa_conversao_perc', 0) < 2 and row.get('ADS_gasto_7d', 0) > 5:
                alertas_exec.append(("Queda de conversão", nome, "Conversão baixa com gasto relevante em ads."))
            if row.get('taxa_cancelamento_7d_perc', 0) > 10:
                alertas_exec.append(("Alto cancelamento", nome, "Taxa acima de 10% no período recente."))
                
        if alertas_exec:
            for alerta in alertas_exec[:8]:
                st.warning(f"**{alerta[1]}**\n\n{alerta[0]}: {alerta[2]}", icon="⚠️")
        elif not alertas_fortes:
            st.success("Nenhum alerta crítico detectado na operação.")

# ==============================================================================
# ABA 2: ATUADOR (O Painel de Aprovação Fino e Elegante)
# ==============================================================================
with aba_atuador:
    st.subheader("Alterações recomendadas")
    st.markdown('<div class="ia-note"><span class="ia-label">Fluxo de confirmação</span><br><b>1. Compare</b> o estado atual com o proposto. &nbsp; <b>2. Leia</b> a força da evidência e a consequência. &nbsp; <b>3. Confirme</b> somente quando a alteração estiver clara. Nenhum botão é executado sem clique explícito.</div>', unsafe_allow_html=True)
    st.info("Fluxo recomendado: analise a recomendação, confira a variação do preço alvo e aprove a ação em 1-clique.")
    
    produtos_agrupados = {}
    for analise in analises:
        dados = analise.get("dados_atuais", {})
        if not dados: continue
        
        iid = dados["item_id"]
        if iid not in produtos_agrupados:
            produtos_agrupados[iid] = {
                "item_id": iid,
                "nome_produto": dados.get("nome_produto", "Produto Desconhecido"),
                "score_max": 0,
                "acoes_pendentes": 0,
                "variacoes": []
            }
        
        produtos_agrupados[iid]["score_max"] = max(produtos_agrupados[iid]["score_max"], analise.get("score_urgencia", 0))
        if analise.get("tipo_acao") != "MANTER":
            produtos_agrupados[iid]["acoes_pendentes"] += 1
        produtos_agrupados[iid]["variacoes"].append(analise)

    produtos_agrupados = dict(sorted(produtos_agrupados.items(), key=lambda x: (x[1]["acoes_pendentes"] > 0, x[1]["score_max"]), reverse=True))

    sem_acoes = True
    for iid, p in produtos_agrupados.items():
        if p["acoes_pendentes"] == 0:
            continue # Oculta produtos perfeitos para manter o foco visual
        
        sem_acoes = False
        score = p["score_max"]
        badge = "🔴 Urgente" if score >= 40 else "🟡 Atenção" if score >= 20 else "🟢 Ok"
        
        with st.expander(f"⚡ {p['nome_produto']} | {p['acoes_pendentes']} SKUs exigem ação | {badge}", expanded=(score >= 40)):
            var_base = p["variacoes"][0]
            
            with st.container(border=True):
                st.markdown(f"**🎯 Motivo da Intervenção:** {var_base.get('recomendacao_executiva', '')}")
                st.caption(f"**Projeção IA:** {var_base.get('analise_de_consequencias', '')}")
            
            st.markdown("#### Grade de Ações")
            for analise_var in p["variacoes"]:
                acao_var = analise_var.get("tipo_acao")
                if acao_var == "MANTER": continue
                
                dados_var = analise_var.get("dados_atuais", {})
                preco_atual = float(dados_var.get("preco_atual") or 0)
                novo_preco = float(analise_var.get("novo_preco_sugerido") or preco_atual)
                modo_execucao, detalhe_execucao = classificar_modo_execucao(acao_var)
                confianca, leitura_evidencia, _ = classificar_confianca_evidencia(dados_var)
                efeito_acao, orientacao_acao = explicar_acao(acao_var)
                
                with st.container(border=True):
                    st.markdown(f"### {rotulo_acao(acao_var)} · {dados_var.get('nome_variacao', 'SKU')}")
                    st.caption(f"O que muda: {efeito_acao} {orientacao_acao}")
                    atual, proposto, decisao = st.columns(3, vertical_alignment="top")
                    with atual:
                        st.markdown("**Hoje**")
                        st.metric("Preço atual", f"R$ {preco_atual:.2f}")
                        st.caption(f"Vendas observadas: {int(dados_var.get('vendas_7d_reais', 0) or 0)} un. em 7 dias")
                        st.caption(f"Resultado operacional: R$ {float(dados_var.get('lucro_liquido_real_7d', 0) or 0):.2f}")
                    with proposto:
                        st.markdown("**Após a ação**")
                        if acao_var in {"AUMENTAR_PRECO", "REDUZIR_PRECO", "CRIAR_PROMOCAO"}:
                            delta_pct = ((novo_preco - preco_atual) / preco_atual * 100) if preco_atual else 0
                            st.metric("Preço proposto", f"R$ {novo_preco:.2f}", delta=f"{delta_pct:+.1f}%")
                        else:
                            st.metric("Preço", "Sem alteração direta")
                        faixa_min, faixa_max = intervalo_demanda_exploratorio(dados_var, float(analise_var.get('previsao_vendas_7d', 0) or 0))
                        st.caption(f"Demanda exploratória: {faixa_min}–{faixa_max} un. / 7 dias")
                        st.caption(f"Resultado projetado: R$ {float(analise_var.get('previsao_lucro_7d', 0) or 0):.2f}")
                    with decisao:
                        st.markdown("**Antes de decidir**")
                        st.caption(f"Evidência: **{confianca}** — {leitura_evidencia}")
                        st.caption("A projeção é uma hipótese. Confira a justificativa e a consequência abaixo antes de confirmar.")
                    st.divider()
                    col_info, col_btn = st.columns([6, 4], vertical_alignment="center")
                    
                    with col_info:
                        if confianca == "Baixa":
                            st.warning(f"Evidência baixa — não automatize sem teste controlado. {leitura_evidencia}")
                        else:
                            st.caption(f"Evidência {confianca.lower()}: {leitura_evidencia}")
                        st.markdown(f"**SKU:** `{dados_var.get('nome_variacao', 'N/A')}`")
                        st.caption(f"**Ação Definida:** {acao_var}")
                        if modo_execucao == "RECOMENDAR":
                            st.info("📌 Alteração Manual Necessária no Seller Center", icon="ℹ️")
                    
                    with col_btn:
                        valido, motivo = validar_sugestao_ia(dados_var, analise_var)
                        if confianca == "Baixa" and modo_execucao == "EXECUTAR":
                            valido = False
                            motivo = "Base histórica insuficiente para execução automática. Valide a hipótese manualmente ou reúna mais dados."
                        if not valido:
                            st.error(f"Bloqueado: {motivo}")
                        elif modo_execucao == "EXECUTAR":
                            st.caption("Confirmar envia esta alteração para a Shopee. Ela fica registrada no histórico de ações.")
                            txt_btn = "Confirmar promoção" if acao_var == "CRIAR_PROMOCAO" else "Confirmar criação do combo" if acao_var == "CRIAR_COMBO" else "Confirmar alteração de preço"
                            if st.button(txt_btn, key=f"exec_{dados_var['model_id']}", use_container_width=True, type="primary"):
                                with st.spinner("Conectando API Shopee..."):
                                    sucesso, msg = processar_acao_api(acao_var, dados_var, analise_var, novo_preco)
                                    if sucesso:
                                        st.toast(f"Sucesso: {msg}", icon="✅")
                                    else:
                                        st.error(msg)
                                        
    if sem_acoes:
        st.success("✅ O Conselho determinou que a estratégia atual está perfeita. Nenhuma intervenção de API é necessária hoje.")

# ==============================================================================
# ABA 3: ELASTICIDADE E PREVISÕES (Sua tabela_exec original)
# ==============================================================================
with aba_previsao:
    st.info("Previsões de 7 dias são cenários operacionais, não previsões estatísticas calibradas. Quando a evidência for baixa, use-as para priorizar investigação ou um teste pequeno — nunca como base única para alterar preço ou orçamento.")
    st.subheader("🧠 Elasticidade e Projeção de Demanda (7d)")
    st.caption("Visão preditiva do impacto do preço no volume de vendas baseado em dados históricos.")
    
    tabela_exec = []
    for a in analises:
        dados = a.get("dados_atuais", {})
        if not dados: continue
        tabela_exec.append({
            "Produto": dados.get("nome_produto", ""),
            "Variação": dados.get("nome_variacao", ""),
            "Ação Alvo": a.get("tipo_acao", "MANTER"),
            "Elasticidade": a.get("elasticidade_preco_volume", dados.get("elasticidade_preco_volume", 0)),
            "Previsão Vendas (7d)": a.get("previsao_vendas_7d", dados.get("previsao_vendas_7d", 0)),
            "Previsão Lucro (7d)": a.get("previsao_lucro_7d", dados.get("previsao_lucro_7d", 0)),
            "Evidência": classificar_confianca_evidencia(dados)[0],
            "Vendas observadas (30d)": dados.get("vendas_30d_macro", 0),
            "Cluster": a.get("cluster_mercado", dados.get("cluster_mercado", "Estável")),
        })
        
    if tabela_exec:
        df_pred = pd.DataFrame(tabela_exec).sort_values(["Previsão Lucro (7d)", "Previsão Vendas (7d)"], ascending=False)
        st.dataframe(
            df_pred, 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "Previsão Vendas (7d)": st.column_config.NumberColumn(format="%d un."),
                "Previsão Lucro (7d)": st.column_config.NumberColumn(format="R$ %.2f")
            }
        )

# ==============================================================================
# ABA 4: DOSSIÊS E RANKINGS (Textos integrais da IA)
# ==============================================================================
with aba_dossies:
    st.markdown("### Transparência da análise")
    data_cache = datetime.fromtimestamp(CACHE_AUDITORIA.stat().st_mtime).strftime('%d/%m/%Y %H:%M') if CACHE_AUDITORIA.exists() else 'não disponível'
    st.markdown(f'<div class="ia-note"><span class="ia-label">Última auditoria em cache</span><br>{data_cache}. A camada determinística calcula vendas, custos de fabricação, ads, tráfego, carrinho, cancelamentos e cobertura de material. O modelo IA recebe esse recorte e devolve recomendações textuais; ele não acessa dados adicionais nem valida causalidade.</div>', unsafe_allow_html=True)
    with st.expander("Ver critérios e limitações metodológicas"):
        st.markdown("""
        - O período operacional principal é de **7 dias**; 30 dias entram como contexto de demanda e tráfego.
        - A elasticidade só é interpretável se houve mudança material de preço e vendas suficientes. Sem isso, correlação não prova que o preço causou a variação de volume.
        - Tráfego e ads são dados no nível do anúncio/produto e são rateados entre variações; use a leitura por SKU como sinal, não como atribuição causal definitiva.
        - Resultado operacional não inclui todos os custos contábeis (por exemplo, mão de obra, impostos fora do repasse e frete, se não estiverem na origem).
        - Recomendações com baixa evidência ficam bloqueadas de execução automática nesta página.
        """)
    st.markdown("### 🎯 Ranking de Potencial de Margem")
    st.caption("Fórmula: Lucro / Gasto Ads + Fator Volume - Fator Cancelamento")
    
    ranking = df_analises.copy()
    ranking['potencial_margem'] = (
        ranking.get('lucro_liquido_real_7d', 0) / (ranking.get('ADS_gasto_7d', 0) + 1)
        + ranking.get('vendas_7d_reais', 0) * 0.2
        - ranking.get('taxa_cancelamento_7d_perc', 0) * 0.5
    )
    ranking_top = ranking.sort_values('potencial_margem', ascending=False).head(15)
    
    if not ranking_top.empty:
        st.dataframe(
            ranking_top[['nome_produto', 'nome_variacao', 'vendas_7d_reais', 'lucro_liquido_real_7d', 'ADS_gasto_7d', 'potencial_margem']], 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "nome_produto": "Produto",
                "nome_variacao": "Variação",
                "vendas_7d_reais": "Vendas (7d)",
                "lucro_liquido_real_7d": st.column_config.NumberColumn("Margem Real", format="R$ %.2f"),
                "ADS_gasto_7d": st.column_config.NumberColumn("Gasto Ads", format="R$ %.2f"),
                "potencial_margem": st.column_config.NumberColumn("Score de Potencial", format="%.2f")
            }
        )

    st.divider()
    st.markdown("### 📖 Dossiês e Pareceres de Diretoria")
    st.caption("Acesse a defesa argumentativa do Conselho C-Level (CFO, CMO, COO) gerada no RunPod para cada produto.")
    
    for iid, p in produtos_agrupados.items():
        var_base = p["variacoes"][0]
        with st.expander(f"Ler Parecer: {p['nome_produto']}"):
            st.markdown(f"**Recomendação Executiva:** {var_base.get('recomendacao_executiva', 'N/A')}")
            
            c1, c2, c3 = st.columns(3)
            with c1: st.info(f"**💰 Parecer CFO (Finanças):**\n\n{var_base.get('relatorio_cfo_financas', 'N/A')}")
            with c2: st.success(f"**🎯 Parecer CMO (Marketing):**\n\n{var_base.get('relatorio_cmo_marketing', 'N/A')}")
            with c3: st.warning(f"**🏭 Parecer COO (Operações):**\n\n{var_base.get('relatorio_coo_operacoes', 'N/A')}")
