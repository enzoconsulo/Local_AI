"""
pages/3___Cerebro_IA.py
========================
Conselho de Administração IA (CFO, CMO, COO) + Atuador Shopee.
"""

import json
import hashlib
import math
import os
import sys
import pandas as pd
import psycopg2.extras
import streamlit as st
from pathlib import Path
from dotenv import load_dotenv
import requests
from loguru import logger
from datetime import datetime
from requests.adapters import HTTPAdapter
from utils.padronizar_texto import padronizar_texto

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

# override=True força o Python a usar a porta 5433 e ignora variáveis falsas do Windows
load_dotenv(ROOT_DIR / "CHAVES_DADOS.env", override=True)

from utils.shopee_core import (
    atualizar_preco_shopee,
    criar_promocao_shopee,
    criar_combo_shopee,
    verificar_status_promocao,
)
from utils.db_pool import get_connection

st.set_page_config(
    page_title="Cérebro Analítico & Atuador",
    page_icon="🧠",
    layout="wide"
)

# Inferência externa direta: não depende de RunPod, LiteLLM local ou GPU ligada.
OPENAI_API_BASE_URL = (os.getenv("OPENAI_API_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
OPENAI_CHAT_COMPLETIONS_URL = (
    OPENAI_API_BASE_URL
    if OPENAI_API_BASE_URL.endswith("/chat/completions")
    else f"{OPENAI_API_BASE_URL}/chat/completions"
)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL_7D = os.getenv("OPENAI_MODEL_7D", "gpt-5.4").strip()
OPENAI_MODEL_30D = os.getenv("OPENAI_MODEL_30D", "gpt-5.5").strip()
OPENAI_REASONING_7D = os.getenv("OPENAI_REASONING_7D", "low").strip().lower()
OPENAI_REASONING_30D = os.getenv("OPENAI_REASONING_30D", "medium").strip().lower()
HTTP_SESSION = requests.Session()
HTTP_SESSION.mount("http://", HTTPAdapter(pool_connections=2, pool_maxsize=4, max_retries=0))
HTTP_SESSION.mount("https://", HTTPAdapter(pool_connections=2, pool_maxsize=4, max_retries=0))

# Caminho para salvar a última auditoria no disco
CACHE_AUDITORIA = ROOT_DIR / "ultima_auditoria.json"
CACHE_AUDITORIA_7D = ROOT_DIR / "ultima_auditoria_7d.json"
CACHE_AUDITORIA_30D = ROOT_DIR / "ultima_auditoria_30d.json"

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
    Atualizada com regras reais de repasse MEI Shopee (20% + R$3) e funil de Tráfego/Ads blindado.
    """
    query = """
    WITH vendas_7d AS (
        SELECT
            i.model_id,
            SUM(i.quantidade) AS qtd_vendida,
            COUNT(DISTINCT p.data_hora_criacao::date) AS dias_com_venda_7d,
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
            COUNT(DISTINCT p.data_hora_criacao::date) AS dias_com_venda_30d,
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
            SUM(COALESCE(impressoes, 0)) AS impressoes_ads,
            SUM(COALESCE(cliques, 0)) AS cliques_ads,
            COUNT(impressoes) AS registros_impressoes_ads,
            COUNT(cliques) AS registros_cliques_ads,
            SUM(COALESCE(investimento, 0)) AS gasto_ads,
            COUNT(DISTINCT data_registro) FILTER (WHERE granularidade_origem = 'DIARIA') AS dias_ads_7d,
            SUM(COALESCE(vendas_gmv, 0)) AS gmv_ads,
            AVG(COALESCE(acos, 0)) AS acos_medio
        FROM fato_ads_performance_produto
        WHERE data_registro >= CURRENT_DATE - INTERVAL '7 days'
        GROUP BY item_id
    ),
    ads_30d AS (
        SELECT
            item_id,
            SUM(COALESCE(impressoes, 0)) AS impressoes_ads_30d,
            SUM(COALESCE(cliques, 0)) AS cliques_ads_30d,
            COUNT(impressoes) AS registros_impressoes_ads_30d,
            COUNT(cliques) AS registros_cliques_ads_30d,
            SUM(COALESCE(investimento, 0)) AS gasto_ads_30d,
            COUNT(DISTINCT data_registro) FILTER (WHERE granularidade_origem = 'DIARIA') AS dias_ads_30d,
            SUM(COALESCE(vendas_gmv, 0)) AS gmv_ads_30d,
            SUM(COALESCE(conversoes, 0)) AS conversoes_ads_30d,
            SUM(COALESCE(itens_vendidos, 0)) AS itens_vendidos_ads_30d
        FROM fato_ads_performance_produto
        WHERE data_registro >= CURRENT_DATE - INTERVAL '30 days'
        GROUP BY item_id
    ),
    trafego_7d AS (
        SELECT
            item_id,
            SUM(COALESCE(impressoes, 0)) AS impressoes_org,
            SUM(COALESCE(cliques, 0)) AS cliques_org,
            COUNT(impressoes) AS registros_impressoes_org,
            COUNT(cliques) AS registros_cliques_org,
            SUM(COALESCE(visitantes_unicos, 0)) AS visitas,
            SUM(COALESCE(adicoes_carrinho, 0)) AS carrinhos,
            COUNT(DISTINCT data) FILTER (WHERE granularidade_origem = 'DIARIA') AS dias_trafego_7d,
            AVG(COALESCE(taxa_rejeicao, 0)) AS rejeicao_media
        FROM fato_trafego_diario
        WHERE data >= CURRENT_DATE - INTERVAL '7 days'
        GROUP BY item_id
    ),
    trafego_30d AS (
        SELECT
            item_id,
            SUM(COALESCE(impressoes, 0)) AS impressoes_org_30d,
            SUM(COALESCE(cliques, 0)) AS cliques_org_30d,
            COUNT(impressoes) AS registros_impressoes_org_30d,
            COUNT(cliques) AS registros_cliques_org_30d,
            SUM(COALESCE(visitantes_unicos, 0)) AS visitas_30d,
            SUM(COALESCE(adicoes_carrinho, 0))  AS carrinhos_30d,
            COUNT(DISTINCT data) FILTER (WHERE granularidade_origem = 'DIARIA') AS dias_trafego_30d,
            AVG(taxa_rejeicao) AS rejeicao_media_30d
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
        COALESCE(ven.dias_com_venda_7d, 0)   AS dias_com_venda_7d,
        COALESCE(v30.qtd_vendida_30d, 0)     AS vendas_30d,
        COALESCE(v30.dias_com_venda_30d, 0)  AS dias_com_venda_30d,
        COALESCE(v30.receita_liquida_30d, 0) AS receita_liquida_30d,
        COALESCE(vant.qtd_vendida_antiga, 0) AS vendas_semana_passada,
        COALESCE(ven.taxa_media_shopee, 0)   AS taxa_shopee_unitaria,
        COALESCE(ven.lucro_liquido_total, 0) AS receita_liquida_7d,

        -- INJEÇÃO: Funil Orgânico e Pago --
        COALESCE(t.impressoes_org, 0)        AS impressoes_org,
        COALESCE(t.cliques_org, 0)           AS cliques_org,
        COALESCE(t.registros_impressoes_org, 0) AS registros_impressoes_org,
        COALESCE(t.registros_cliques_org, 0) AS registros_cliques_org,
        COALESCE(t.rejeicao_media, 0)        AS rejeicao_media,
        COALESCE(a.impressoes_ads, 0)        AS impressoes_ads,
        COALESCE(a.cliques_ads, 0)           AS cliques_ads,
        COALESCE(a.registros_impressoes_ads, 0) AS registros_impressoes_ads,
        COALESCE(a.registros_cliques_ads, 0) AS registros_cliques_ads,
        COALESCE(a.gmv_ads, 0)               AS gmv_ads,
        COALESCE(a.acos_medio, 0)            AS acos_medio,
        ------------------------------------

        COALESCE(t.visitas, 0)               AS visitas_7d,
        COALESCE(t.carrinhos, 0)             AS carrinhos_7d,
        COALESCE(t.dias_trafego_7d, 0)       AS dias_trafego_7d,
        COALESCE(a.gasto_ads, 0)             AS gasto_ads_7d,
        COALESCE(a.dias_ads_7d, 0)           AS dias_ads_7d,

        COALESCE(t30.visitas_30d, 0)         AS visitas_30d,
        COALESCE(t30.carrinhos_30d, 0)       AS carrinhos_30d,
        COALESCE(t30.dias_trafego_30d, 0)    AS dias_trafego_30d,
        COALESCE(t30.impressoes_org_30d, 0)  AS impressoes_org_30d,
        COALESCE(t30.cliques_org_30d, 0)     AS cliques_org_30d,
        COALESCE(t30.registros_impressoes_org_30d, 0) AS registros_impressoes_org_30d,
        COALESCE(t30.registros_cliques_org_30d, 0) AS registros_cliques_org_30d,
        COALESCE(a30.gasto_ads_30d, 0)       AS gasto_ads_30d,
        COALESCE(a30.dias_ads_30d, 0)        AS dias_ads_30d,
        COALESCE(a30.impressoes_ads_30d, 0)  AS impressoes_ads_30d,
        COALESCE(a30.cliques_ads_30d, 0)     AS cliques_ads_30d,
        COALESCE(a30.registros_impressoes_ads_30d, 0) AS registros_impressoes_ads_30d,
        COALESCE(a30.registros_cliques_ads_30d, 0) AS registros_cliques_ads_30d,
        COALESCE(a30.gmv_ads_30d, 0)         AS gmv_ads_30d,
        COALESCE(a30.conversoes_ads_30d, 0)  AS conversoes_ads_30d,
        COALESCE(a30.itens_vendidos_ads_30d, 0) AS itens_vendidos_ads_30d,

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
            taxa_shopee_unitaria = (preco * 0.20) + 3.00

        margem_unitaria_real = preco - taxa_shopee_unitaria - custo_fab

        qtd_variacoes = max(1, int(r["qtd_variacoes_produto"] or 1))

        gasto_ads    = float(r["gasto_ads_7d"]) / qtd_variacoes
        visitas      = int(r["visitas_7d"]) // qtd_variacoes
        carrinhos    = int(r["carrinhos_7d"]) // qtd_variacoes
        gasto_ads_30d = float(r["gasto_ads_30d"] or 0) / qtd_variacoes
        visitas_30d = int(r["visitas_30d"] or 0) // qtd_variacoes
        carrinhos_30d = int(r["carrinhos_30d"] or 0) // qtd_variacoes

        # INJEÇÃO: Processamento do Funil Rateado
        impressoes_org = int(r["impressoes_org"] or 0) // qtd_variacoes
        cliques_org = int(r["cliques_org"] or 0) // qtd_variacoes
        rejeicao_media = float(r["rejeicao_media"] or 0)
        org_impressoes_disponiveis = int(r["registros_impressoes_org"] or 0) > 0 and (impressoes_org > 0 or visitas == 0)
        org_cliques_disponiveis = int(r["registros_cliques_org"] or 0) > 0 and (cliques_org > 0 or visitas == 0)

        impressoes_ads = int(r["impressoes_ads"] or 0) // qtd_variacoes
        cliques_ads = int(r["cliques_ads"] or 0) // qtd_variacoes
        gmv_ads = float(r["gmv_ads"] or 0) / qtd_variacoes
        acos_medio = float(r["acos_medio"] or 0)
        ads_impressoes_disponiveis = int(r["registros_impressoes_ads"] or 0) > 0 and (impressoes_ads > 0 or gasto_ads == 0)
        ads_cliques_disponiveis = int(r["registros_cliques_ads"] or 0) > 0 and (cliques_ads > 0 or gasto_ads == 0)

        ctr_org = round((cliques_org / impressoes_org) * 100, 2) if org_impressoes_disponiveis and org_cliques_disponiveis and impressoes_org > 0 else None
        ctr_ads = round((cliques_ads / impressoes_ads) * 100, 2) if ads_impressoes_disponiveis and ads_cliques_disponiveis and impressoes_ads > 0 else None

        impressoes_org_30d = int(r["impressoes_org_30d"] or 0) // qtd_variacoes
        cliques_org_30d = int(r["cliques_org_30d"] or 0) // qtd_variacoes
        org_impressoes_30d_disponiveis = int(r["registros_impressoes_org_30d"] or 0) > 0 and (impressoes_org_30d > 0 or visitas_30d == 0)
        org_cliques_30d_disponiveis = int(r["registros_cliques_org_30d"] or 0) > 0 and (cliques_org_30d > 0 or visitas_30d == 0)
        ctr_org_30d = round((cliques_org_30d / impressoes_org_30d) * 100, 2) if org_impressoes_30d_disponiveis and org_cliques_30d_disponiveis and impressoes_org_30d > 0 else None

        impressoes_ads_30d = int(r["impressoes_ads_30d"] or 0) // qtd_variacoes
        cliques_ads_30d = int(r["cliques_ads_30d"] or 0) // qtd_variacoes
        ads_impressoes_30d_disponiveis = int(r["registros_impressoes_ads_30d"] or 0) > 0 and (impressoes_ads_30d > 0 or gasto_ads_30d == 0)
        ads_cliques_30d_disponiveis = int(r["registros_cliques_ads_30d"] or 0) > 0 and (cliques_ads_30d > 0 or gasto_ads_30d == 0)
        ctr_ads_30d = round((cliques_ads_30d / impressoes_ads_30d) * 100, 2) if ads_impressoes_30d_disponiveis and ads_cliques_30d_disponiveis and impressoes_ads_30d > 0 else None
        gmv_ads_30d = float(r["gmv_ads_30d"] or 0) / qtd_variacoes

        # O ESCUDO ANTI-ALUCINAÇÃO:
        # Se um item teve visitas/gasto, mas impressões vieram 0, significa que a planilha upada não tinha a coluna impressões.
        # Nesses casos, passamos 'None' em vez de '0' para a IA não achar que o produto sofreu shadowban.
        dados_org_completos = True if impressoes_org > 0 or visitas == 0 else False
        dados_ads_completos = True if impressoes_ads > 0 or gasto_ads == 0 else False

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
            "COBERTURA_dias_com_venda_7d": int(r["dias_com_venda_7d"] or 0),
            "COBERTURA_dias_com_venda_30d": int(r["dias_com_venda_30d"] or 0),
            "tendencia_vendas_WoW_perc":    tendencia_perc,
            "ritmo_7d_vs_30d_perc":         ritmo_7d_vs_30d_perc,
            "taxa_abandono_carrinho_perc":  taxa_abandono,
            "lucro_liquido_real_7d":        round(lucro_operacional, 2),
            "lucro_liquido_real_30d":       round(lucro_operacional_30d, 2),
            "REPUTACAO_estrelas":               float(r["estrelas"]),
            "REPUTACAO_curtidas_favoritos":     r["curtidas_favoritos"],
            "LOGISTICA_capacidade_material_restante": capacidade_maxima,
            "LOGISTICA_dias_estoque_restante":  dias_estoque,
            "LOGISTICA_dias_estoque_base_30d":  dias_estoque_30d,

            # --- INJEÇÃO DO FUNIL DE DADOS ---
            "TRAFEGO_ORG_impressoes_7d": impressoes_org if org_impressoes_disponiveis else None,
            "TRAFEGO_ORG_cliques_7d": cliques_org if org_cliques_disponiveis else None,
            "TRAFEGO_ORG_ctr_perc": ctr_org,
            "TRAFEGO_ORG_taxa_rejeicao_perc": rejeicao_media if dados_org_completos else None,

            "ADS_impressoes_7d": impressoes_ads if ads_impressoes_disponiveis else None,
            "ADS_cliques_7d": cliques_ads if ads_cliques_disponiveis else None,
            "ADS_ctr_perc": ctr_ads,
            "ADS_gmv_7d": round(gmv_ads, 2),
            "ADS_acos_medio": round(acos_medio, 2),
            "TRAFEGO_ORG_impressoes_30d": impressoes_org_30d if org_impressoes_30d_disponiveis else None,
            "TRAFEGO_ORG_cliques_30d": cliques_org_30d if org_cliques_30d_disponiveis else None,
            "TRAFEGO_ORG_ctr_30d_perc": ctr_org_30d,
            "ADS_impressoes_30d": impressoes_ads_30d if ads_impressoes_30d_disponiveis else None,
            "ADS_cliques_30d": cliques_ads_30d if ads_cliques_30d_disponiveis else None,
            "ADS_ctr_30d_perc": ctr_ads_30d,
            "ADS_gmv_30d": round(gmv_ads_30d, 2),
            # ---------------------------------

            "TRAFEGO_visitas_7d":           visitas,
            "TRAFEGO_adicoes_carrinho_7d":  carrinhos,
            "COBERTURA_dias_trafego_7d": int(r["dias_trafego_7d"] or 0),
            "TRAFEGO_taxa_conversao_perc":  taxa_conversao,
            "TRAFEGO_visitas_30d":          visitas_30d,
            "TRAFEGO_adicoes_carrinho_30d": carrinhos_30d,
            "COBERTURA_dias_trafego_30d": int(r["dias_trafego_30d"] or 0),
            "TRAFEGO_taxa_conversao_30d_perc": taxa_conversao_30d,
            "taxa_abandono_carrinho_30d_perc": taxa_abandono_30d,
            "ADS_gasto_7d":   round(gasto_ads, 2),
            "ADS_gasto_7d_total_anuncio": float(r["gasto_ads_7d"] or 0),
            "COBERTURA_dias_ads_7d": int(r["dias_ads_7d"] or 0),
            "ADS_roas_atual": roas_atual,
            "ADS_gasto_30d": round(gasto_ads_30d, 2),
            "ADS_gasto_30d_total_anuncio": float(r["gasto_ads_30d"] or 0),
            "COBERTURA_dias_ads_30d": int(r["dias_ads_30d"] or 0),
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

    return enriquecer_dossie_com_memoria(dossie)


@st.cache_data(ttl=60, show_spinner=False)
def _memoria_analitica_disponivel() -> bool:
    """Permite iniciar o app antes da migração 08, sem mascarar uma falha de banco."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('public.ia_execucoes_analiticas')")
                return cur.fetchone()[0] is not None
    except Exception as exc:
        logger.warning(f"Não foi possível verificar memória analítica: {exc}")
        return False


@st.cache_data(ttl=60, show_spinner=False)
def _cache_semantico_disponivel() -> bool:
    """Confirma a migração 10; sem ela, mantém persistência legada e desliga só o cache."""
    if not _memoria_analitica_disponivel():
        return False
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = 'ia_snapshots_variacao'
                          AND column_name = 'fingerprint_entrada'
                    )
                """)
                return bool(cur.fetchone()[0])
    except Exception as exc:
        logger.warning(f"Não foi possível verificar a migração do cache semântico: {exc}")
        return False


def enriquecer_dossie_com_memoria(dossie: list[dict]) -> list[dict]:
    """Anexa a última estratégia mensal e a última avaliação de ação por variação."""
    if not dossie or not _memoria_analitica_disponivel():
        return dossie

    model_ids = [int(d["model_id"]) for d in dossie if d.get("model_id") is not None]
    if not model_ids:
        return dossie

    query = """
        WITH ultimo_mensal AS (
            SELECT DISTINCT ON (s.model_id)
                s.model_id, e.criado_em, s.metricas_observadas, s.previsoes,
                s.recomendacao, s.qualidade_evidencia
            FROM ia_snapshots_variacao s
            JOIN ia_execucoes_analiticas e ON e.id_execucao = s.id_execucao
            WHERE e.horizonte_dias = 30 AND e.status = 'CONCLUIDA'
              AND s.model_id = ANY(%s)
            ORDER BY s.model_id, e.criado_em DESC
        ), ultima_avaliacao AS (
            SELECT DISTINCT ON (a.model_id)
                a.model_id, a.avaliado_em, a.comparacao, a.status
            FROM ia_avaliacoes_acoes a
            WHERE a.model_id = ANY(%s)
            ORDER BY a.model_id, a.avaliado_em DESC
        )
        SELECT m.model_id, m.criado_em, m.metricas_observadas, m.previsoes,
               m.recomendacao, m.qualidade_evidencia,
               a.avaliado_em, a.comparacao, a.status AS status_avaliacao
        FROM ultimo_mensal m
        LEFT JOIN ultima_avaliacao a ON a.model_id = m.model_id;
    """
    memoria_por_modelo = {}
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(query, (model_ids, model_ids))
                for linha in cur.fetchall():
                    memoria_por_modelo[int(linha["model_id"])] = {
                        "ultima_analise_30d_em": linha["criado_em"].isoformat() if linha["criado_em"] else None,
                        "qualidade_evidencia": linha["qualidade_evidencia"],
                        "metricas_observadas": linha["metricas_observadas"] or {},
                        "previsoes": linha["previsoes"] or {},
                        "recomendacao": linha["recomendacao"] or {},
                        "ultima_avaliacao_em": linha["avaliado_em"].isoformat() if linha["avaliado_em"] else None,
                        "comparacao_ultima_acao": linha["comparacao"] or {},
                        "status_ultima_avaliacao": linha["status_avaliacao"],
                    }
    except Exception as exc:
        logger.warning(f"Memória analítica indisponível; auditoria seguirá sem histórico persistido: {exc}")
        return dossie

    for dados in dossie:
        memoria = memoria_por_modelo.get(int(dados["model_id"]))
        dados["MEMORIA_ESTRATEGICA_30D"] = memoria or None
    return dossie


def calcular_fingerprint_entrada(dados: dict, horizonte: str) -> str:
    """Hash determinístico dos fatos que realmente influenciam cada horizonte."""
    campos_7d = {
        "item_id", "model_id", "nome_produto", "nome_variacao", "preco_atual",
        "custo_fab_real", "vendas_7d_reais", "tendencia_vendas_WoW_perc",
        "lucro_liquido_real_7d", "TRAFEGO_visitas_7d", "TRAFEGO_adicoes_carrinho_7d",
        "TRAFEGO_taxa_conversao_perc", "taxa_abandono_carrinho_perc",
        "ADS_gasto_7d", "ADS_roas_atual", "taxa_cancelamento_7d_perc",
        "estoque_shopee_hoje", "LOGISTICA_capacidade_material_restante",
        "LOGISTICA_dias_estoque_restante", "previsao_vendas_7d", "previsao_lucro_7d",
        "TRAFEGO_ORG_impressoes_7d", "TRAFEGO_ORG_cliques_7d", "TRAFEGO_ORG_ctr_perc",
        "ADS_impressoes_7d", "ADS_cliques_7d", "ADS_ctr_perc", "ADS_acos_medio",
        "MEMORIA_ESTRATEGICA_30D", "historico_acoes_passadas",
    }
    if horizonte == "30d":
        # A saída mensal anterior não é um fato novo e não pode invalidar o próprio cache.
        # Apenas a avaliação observada de ações passadas entra como nova evidência.
        selecionados = {k: v for k, v in dados.items() if k != "MEMORIA_ESTRATEGICA_30D"}
        memoria = dados.get("MEMORIA_ESTRATEGICA_30D") or {}
        selecionados["RESULTADO_OBSERVADO_ACAO"] = {
            "ultima_avaliacao_em": memoria.get("ultima_avaliacao_em"),
            "comparacao_ultima_acao": memoria.get("comparacao_ultima_acao"),
            "status_ultima_avaliacao": memoria.get("status_ultima_avaliacao"),
        }
    else:
        selecionados = {k: dados.get(k) for k in sorted(campos_7d)}
    selecionados["CONFIGURACAO_IA"] = {
        "provedor": "openai",
        "modelo": OPENAI_MODEL_7D if horizonte == "7d" else OPENAI_MODEL_30D,
        "reasoning_effort": OPENAI_REASONING_7D if horizonte == "7d" else OPENAI_REASONING_30D,
        "versao_prompt": "openai-json-v1",
    }
    serializado = json.dumps(selecionados, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(serializado.encode("utf-8")).hexdigest()


def persistir_auditoria_analitica(horizonte: str, resultados: list[dict]) -> str | None:
    """Persiste uma auditoria e snapshots imutáveis sem duplicar os fatos do DW."""
    if not resultados or not _memoria_analitica_disponivel():
        return None

    horizonte_dias = 7 if horizonte == "7d" else 30
    modelo_ia = f"openai:{OPENAI_MODEL_7D if horizonte == '7d' else OPENAI_MODEL_30D}"
    snapshots = []
    for resultado in resultados:
        dados = resultado.get("dados_atuais", {})
        if not dados.get("model_id") or not dados.get("item_id"):
            continue
        previsoes = {
            chave: resultado.get(chave, dados.get(chave))
            for chave in ("previsao_vendas_7d", "previsao_lucro_7d", "previsao_vendas_30d", "previsao_lucro_30d")
        }
        recomendacao = {
            chave: resultado.get(chave)
            for chave in (
                "tipo_acao", "novo_preco_sugerido", "horas_duracao_promocao",
                "recomendacao_executiva", "plano_curto_prazo_7d", "plano_longo_prazo_30d",
                "analise_de_consequencias", "cluster_mercado", "relatorio_cfo_financas",
                "relatorio_cmo_marketing", "relatorio_coo_operacoes", "plano_acao_shopee",
                "elasticidade_preco_volume", "falha_modelo_externo"
            ) if resultado.get(chave) is not None
        }
        snapshots.append((
            int(dados["item_id"]), int(dados["model_id"]),
            int(resultado.get("score_urgencia", 0) or 0),
            classificar_confianca_evidencia(dados)[0],
            resultado.get("tipo_acao", "MANTER"), calcular_fingerprint_entrada(dados, horizonte),
            json.dumps(dados, ensure_ascii=False),
            json.dumps(previsoes, ensure_ascii=False), json.dumps(recomendacao, ensure_ascii=False),
        ))

    if not snapshots:
        return None

    cobertura = {
        "variacoes": len(snapshots),
        "dias_trafego_30d_mediana": int(pd.Series([
            s.get("dados_atuais", {}).get("COBERTURA_dias_trafego_30d", 0) for s in resultados
        ]).median() or 0),
    }
    resumo = {
        "acoes_recomendadas": sum(1 for r in resultados if r.get("tipo_acao") not in (None, "MANTER")),
        "falhas_modelo_externo": sum(1 for r in resultados if r.get("falha_modelo_externo")),
        "resultado_operacional_observado": round(sum(
            float(r.get("dados_atuais", {}).get(f"lucro_liquido_real_{horizonte_dias}d", 0) or 0)
            for r in resultados
        ), 2),
    }
    status_execucao = "PARCIAL" if resumo["falhas_modelo_externo"] else "CONCLUIDA"
    cache_semantico = _cache_semantico_disponivel()
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO ia_execucoes_analiticas
                        (horizonte_dias, inicio_janela, fim_janela, modelo_ia, total_variacoes,
                         cobertura_dados, resumo_executivo, status)
                    VALUES (%s, CURRENT_DATE - (%s * INTERVAL '1 day'), CURRENT_DATE, %s, %s, %s::jsonb, %s::jsonb, %s)
                    RETURNING id_execucao;
                """, (
                    horizonte_dias, horizonte_dias, modelo_ia, len(snapshots),
                    json.dumps(cobertura), json.dumps(resumo), status_execucao,
                ))
                id_execucao = str(cur.fetchone()[0])
                if cache_semantico:
                    psycopg2.extras.execute_values(cur, """
                        INSERT INTO ia_snapshots_variacao
                            (id_execucao, item_id, model_id, score_urgencia, qualidade_evidencia,
                             tipo_acao_recomendada, fingerprint_entrada, metricas_observadas, previsoes, recomendacao)
                        VALUES %s
                    """, [
                        (id_execucao, *snapshot)
                        for snapshot in snapshots
                    ], template="(%s::uuid, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)")
                else:
                    psycopg2.extras.execute_values(cur, """
                        INSERT INTO ia_snapshots_variacao
                            (id_execucao, item_id, model_id, score_urgencia, qualidade_evidencia,
                             tipo_acao_recomendada, metricas_observadas, previsoes, recomendacao)
                        VALUES %s
                    """, [
                        (id_execucao, *snapshot[:5], *snapshot[6:])
                        for snapshot in snapshots
                    ], template="(%s::uuid, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)")
            conn.commit()
        return id_execucao
    except Exception as exc:
        logger.error(f"Falha ao persistir auditoria analítica: {exc}")
        return None


@st.cache_data(ttl=60, show_spinner=False)
def _checkpoint_analitico_disponivel() -> bool:
    """Exige as migrations 10 e 11 antes de ativar retomada por lote."""
    if not _cache_semantico_disponivel():
        return False
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = 'ia_execucoes_analiticas'
                          AND column_name = 'atualizado_em'
                    )
                """)
                return bool(cur.fetchone()[0])
    except Exception as exc:
        logger.warning(f"Checkpoint analítico indisponível: {exc}")
        return False


def _montar_snapshots_analiticos(horizonte: str, resultados: list[dict]) -> list[tuple]:
    """Converte resultados em registros idempotentes de snapshot para uma mesma execução."""
    snapshots = []
    for resultado in resultados:
        dados = resultado.get("dados_atuais", {})
        if not dados.get("model_id") or not dados.get("item_id"):
            continue
        previsoes = {
            chave: resultado.get(chave, dados.get(chave))
            for chave in (
                "previsao_vendas_7d", "previsao_lucro_7d",
                "previsao_vendas_30d", "previsao_lucro_30d",
            )
        }
        recomendacao = {
            chave: resultado.get(chave)
            for chave in (
                "tipo_acao", "novo_preco_sugerido", "horas_duracao_promocao",
                "recomendacao_executiva", "plano_curto_prazo_7d", "plano_longo_prazo_30d",
                "analise_de_consequencias", "cluster_mercado", "relatorio_cfo_financas",
                "relatorio_cmo_marketing", "relatorio_coo_operacoes", "plano_acao_shopee",
                "elasticidade_preco_volume", "falha_modelo_externo",
            ) if resultado.get(chave) is not None
        }
        snapshots.append((
            int(dados["item_id"]), int(dados["model_id"]),
            int(resultado.get("score_urgencia", 0) or 0),
            classificar_confianca_evidencia(dados)[0],
            resultado.get("tipo_acao", "MANTER"),
            calcular_fingerprint_entrada(dados, horizonte),
            json.dumps(dados, ensure_ascii=False),
            json.dumps(previsoes, ensure_ascii=False),
            json.dumps(recomendacao, ensure_ascii=False),
        ))
    return snapshots


def iniciar_ou_retomar_checkpoint(
    horizonte: str, total_variacoes: int, cobertura: dict,
) -> tuple[str | None, bool]:
    """Abre uma execução durável ou retoma a execução incompleta da janela corrente."""
    if not _checkpoint_analitico_disponivel():
        return None, False
    horizonte_dias = 7 if horizonte == "7d" else 30
    modelo_ia = f"openai:{OPENAI_MODEL_7D if horizonte == '7d' else OPENAI_MODEL_30D}"
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Não retoma uma janela móvel expirada; preserva seus lotes válidos como parcial.
                cur.execute("""
                    UPDATE ia_execucoes_analiticas
                    SET status = 'PARCIAL',
                        resumo_executivo = COALESCE(resumo_executivo, '{}'::jsonb)
                            || jsonb_build_object('motivo_parcial', 'Janela expirada antes da conclusão'),
                        atualizado_em = CURRENT_TIMESTAMP
                    WHERE horizonte_dias = %s
                      AND fim_janela < CURRENT_DATE
                      AND status = 'EM_ANDAMENTO';
                """, (horizonte_dias,))
                cur.execute("""
                    SELECT id_execucao
                    FROM ia_execucoes_analiticas
                    WHERE horizonte_dias = %s
                      AND fim_janela = CURRENT_DATE
                      AND status = 'EM_ANDAMENTO'
                    ORDER BY atualizado_em DESC
                    LIMIT 1;
                """, (horizonte_dias,))
                existente = cur.fetchone()
                if existente:
                    id_execucao = str(existente[0])
                    cur.execute("""
                        UPDATE ia_execucoes_analiticas
                        SET total_variacoes = %s,
                            modelo_ia = %s,
                            cobertura_dados = %s::jsonb,
                            atualizado_em = CURRENT_TIMESTAMP
                        WHERE id_execucao = %s::uuid;
                    """, (total_variacoes, modelo_ia, json.dumps(cobertura), id_execucao))
                    retomada = True
                else:
                    cur.execute("""
                        INSERT INTO ia_execucoes_analiticas
                            (horizonte_dias, inicio_janela, fim_janela, modelo_ia, total_variacoes,
                             cobertura_dados, resumo_executivo, status, atualizado_em)
                        VALUES (
                            %s, CURRENT_DATE - (%s * INTERVAL '1 day'), CURRENT_DATE, %s, %s,
                            %s::jsonb, %s::jsonb, 'EM_ANDAMENTO', CURRENT_TIMESTAMP
                        )
                        RETURNING id_execucao;
                    """, (
                        horizonte_dias, horizonte_dias, modelo_ia, total_variacoes,
                        json.dumps(cobertura), json.dumps({"checkpoint": True}),
                    ))
                    id_execucao = str(cur.fetchone()[0])
                    retomada = False
            conn.commit()
        return id_execucao, retomada
    except Exception as exc:
        logger.error(f"Não foi possível abrir checkpoint analítico: {exc}")
        return None, False


def persistir_lote_no_checkpoint(id_execucao: str, horizonte: str, resultados: list[dict]) -> bool:
    """Confirma cada lote em transação própria; uma queda não apaga lotes anteriores."""
    snapshots = _montar_snapshots_analiticos(horizonte, resultados)
    if not snapshots:
        return True
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, """
                    INSERT INTO ia_snapshots_variacao
                        (id_execucao, item_id, model_id, score_urgencia, qualidade_evidencia,
                         tipo_acao_recomendada, fingerprint_entrada, metricas_observadas, previsoes, recomendacao)
                    VALUES %s
                    ON CONFLICT (id_execucao, model_id) DO UPDATE SET
                        item_id = EXCLUDED.item_id,
                        score_urgencia = EXCLUDED.score_urgencia,
                        qualidade_evidencia = EXCLUDED.qualidade_evidencia,
                        tipo_acao_recomendada = EXCLUDED.tipo_acao_recomendada,
                        fingerprint_entrada = EXCLUDED.fingerprint_entrada,
                        metricas_observadas = EXCLUDED.metricas_observadas,
                        previsoes = EXCLUDED.previsoes,
                        recomendacao = EXCLUDED.recomendacao,
                        criado_em = CURRENT_TIMESTAMP;
                """, [(id_execucao, *snapshot) for snapshot in snapshots],
                template="(%s::uuid, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)")
                cur.execute("""
                    UPDATE ia_execucoes_analiticas
                    SET atualizado_em = CURRENT_TIMESTAMP
                    WHERE id_execucao = %s::uuid;
                """, (id_execucao,))
            conn.commit()
        return True
    except Exception as exc:
        logger.error(f"Falha ao confirmar lote no checkpoint: {exc}")
        return False


def _resultado_de_snapshot(anterior, dados: dict, horizonte: str, retomado: bool) -> dict:
    return {
        **(anterior["previsoes"] or {}),
        **(anterior["recomendacao"] or {}),
        "item_id": int(dados["item_id"]),
        "model_id": int(dados["model_id"]),
        "dados_atuais": dados,
        "score_urgencia": calcular_score_urgencia(dados),
        "dias_estoque": calcular_dias_estoque(dados),
        "horizonte_auditoria": horizonte,
        "resultado_reutilizado": not retomado,
        "resultado_retomado": retomado,
        "id_execucao_analitica": str(anterior["id_execucao"]),
    }


def separar_resultados_do_checkpoint(
    id_execucao: str, horizonte: str, dossie: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Recupera somente snapshots do checkpoint ainda compatíveis com os fatos atuais."""
    if not id_execucao or not dossie:
        return [], dossie
    entradas = [
        {"model_id": int(d["model_id"]), "fingerprint_entrada": calcular_fingerprint_entrada(d, horizonte)}
        for d in dossie
    ]
    query = """
        WITH entradas AS (
            SELECT x.model_id, x.fingerprint_entrada
            FROM jsonb_to_recordset(%s::jsonb)
                AS x(model_id BIGINT, fingerprint_entrada TEXT)
        )
        SELECT s.id_execucao, s.model_id, s.previsoes, s.recomendacao
        FROM ia_snapshots_variacao s
        JOIN entradas i
          ON i.model_id = s.model_id
         AND i.fingerprint_entrada::CHAR(64) = s.fingerprint_entrada
        WHERE s.id_execucao = %s::uuid
          AND COALESCE((s.recomendacao->>'falha_modelo_externo')::boolean, FALSE) = FALSE;
    """
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(query, (json.dumps(entradas), id_execucao))
                anteriores = {int(r["model_id"]): r for r in cur.fetchall()}
    except Exception as exc:
        logger.warning(f"Não foi possível recuperar checkpoint: {exc}")
        return [], dossie

    retomados, pendentes = [], []
    for dados in dossie:
        anterior = anteriores.get(int(dados["model_id"]))
        if anterior:
            retomados.append(_resultado_de_snapshot(anterior, dados, horizonte, retomado=True))
        else:
            pendentes.append(dados)
    return retomados, pendentes


def finalizar_checkpoint(
    id_execucao: str, horizonte: str, resultados: list[dict], total_esperado: int,
) -> bool:
    """Fecha a execução apenas após validar cobertura e preserva PARCIAL quando necessário."""
    horizonte_dias = 7 if horizonte == "7d" else 30
    cobertura = {
        "variacoes": len(resultados),
        "dias_trafego_30d_mediana": int(pd.Series([
            r.get("dados_atuais", {}).get("COBERTURA_dias_trafego_30d", 0) for r in resultados
        ]).median() or 0),
    }
    resumo = {
        "checkpoint": True,
        "acoes_recomendadas": sum(1 for r in resultados if r.get("tipo_acao") not in (None, "MANTER")),
        "falhas_modelo_externo": sum(1 for r in resultados if r.get("falha_modelo_externo")),
        "resultado_operacional_observado": round(sum(
            float(r.get("dados_atuais", {}).get(f"lucro_liquido_real_{horizonte_dias}d", 0) or 0)
            for r in resultados
        ), 2),
    }
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM ia_snapshots_variacao WHERE id_execucao = %s::uuid", (id_execucao,))
                total_persistido = int(cur.fetchone()[0])
                status = (
                    "CONCLUIDA"
                    if total_persistido >= total_esperado and not resumo["falhas_modelo_externo"]
                    else "PARCIAL"
                )
                cur.execute("""
                    UPDATE ia_execucoes_analiticas
                    SET total_variacoes = %s,
                        cobertura_dados = %s::jsonb,
                        resumo_executivo = %s::jsonb,
                        status = %s,
                        atualizado_em = CURRENT_TIMESTAMP
                    WHERE id_execucao = %s::uuid;
                """, (
                    total_esperado, json.dumps(cobertura), json.dumps(resumo), status, id_execucao,
                ))
            conn.commit()
        return status == "CONCLUIDA"
    except Exception as exc:
        logger.error(f"Falha ao finalizar checkpoint: {exc}")
        return False


def separar_resultados_reutilizaveis(horizonte: str, dossie: list[dict]) -> tuple[list[dict], list[dict]]:
    """Reutiliza inferência recente somente quando o fingerprint dos fatos é idêntico."""
    if not dossie or not _cache_semantico_disponivel():
        return [], dossie
    dias_cache = 1 if horizonte == "7d" else 7
    entradas = [
        {
            "model_id": int(dados["model_id"]),
            "fingerprint_entrada": calcular_fingerprint_entrada(dados, horizonte),
        }
        for dados in dossie
    ]
    query = """
        WITH entradas AS (
            SELECT x.model_id, x.fingerprint_entrada
            FROM jsonb_to_recordset(%s::jsonb)
                AS x(model_id BIGINT, fingerprint_entrada TEXT)
        )
        SELECT DISTINCT ON (s.model_id)
            s.id_execucao, s.model_id, s.fingerprint_entrada, s.previsoes, s.recomendacao
        FROM ia_snapshots_variacao s
        JOIN ia_execucoes_analiticas e ON e.id_execucao = s.id_execucao
        JOIN entradas i
          ON i.model_id = s.model_id
         AND i.fingerprint_entrada::CHAR(64) = s.fingerprint_entrada
        WHERE e.horizonte_dias = %s AND e.status IN ('CONCLUIDA', 'PARCIAL')
          AND e.criado_em >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')
          AND s.fingerprint_entrada IS NOT NULL
          AND COALESCE((s.recomendacao->>'falha_modelo_externo')::boolean, FALSE) = FALSE
        ORDER BY s.model_id, e.criado_em DESC;
    """
    anteriores = {}
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(query, (json.dumps(entradas), 7 if horizonte == "7d" else 30, dias_cache))
                anteriores = {int(r["model_id"]): r for r in cur.fetchall()}
    except Exception as exc:
        logger.warning(f"Cache semântico indisponível; todos os SKUs serão analisados: {exc}")
        return [], dossie

    reutilizados, pendentes = [], []
    for dados in dossie:
        anterior = anteriores.get(int(dados["model_id"]))
        if not anterior:
            pendentes.append(dados)
            continue
        resultado = {
            **(anterior["previsoes"] or {}),
            **(anterior["recomendacao"] or {}),
            "item_id": int(dados["item_id"]),
            "model_id": int(dados["model_id"]),
            "dados_atuais": dados,
            "score_urgencia": calcular_score_urgencia(dados),
            "dias_estoque": calcular_dias_estoque(dados),
            "horizonte_auditoria": horizonte,
            "resultado_reutilizado": True,
            "id_execucao_analitica": str(anterior["id_execucao"]),
        }
        reutilizados.append(resultado)
    return reutilizados, pendentes


def avaliar_acoes_maduras(dossie_atual: list[dict]) -> int:
    """Compara ações com pelo menos 7 dias ao estado atual; registra associação, não causalidade."""
    if not dossie_atual or not _memoria_analitica_disponivel():
        return 0
    atuais = {int(d["model_id"]): d for d in dossie_atual if d.get("model_id") is not None}
    if not atuais:
        return 0

    query = """
        SELECT l.id_log, l.id_execucao_origem, l.item_id, l.model_id, l.data_aplicacao,
               l.impacto_projetado, s.metricas_observadas
        FROM log_acoes_shopee l
        JOIN ia_snapshots_variacao s
          ON s.id_execucao = l.id_execucao_origem AND s.model_id = l.model_id
        LEFT JOIN ia_avaliacoes_acoes a ON a.id_log = l.id_log
        WHERE l.status_api = 'SUCESSO'
          AND l.model_id = ANY(%s)
          AND l.data_aplicacao <= CURRENT_TIMESTAMP - INTERVAL '7 days'
          AND a.id_log IS NULL;
    """
    avaliadas = 0
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(query, (list(atuais),))
                pendentes = cur.fetchall()
                for acao in pendentes:
                    atual = atuais[int(acao["model_id"])]
                    baseline = acao["metricas_observadas"] or {}
                    previsto = acao["impacto_projetado"] or {}
                    observado = {
                        "vendas_7d": atual.get("vendas_7d_reais"),
                        "lucro_7d": atual.get("lucro_liquido_real_7d"),
                        "conversao_7d": atual.get("TRAFEGO_taxa_conversao_perc"),
                    }
                    comparacao = {
                        "delta_vendas_vs_baseline": (atual.get("vendas_7d_reais", 0) or 0) - (baseline.get("vendas_7d_reais", 0) or 0),
                        "delta_lucro_vs_baseline": round((atual.get("lucro_liquido_real_7d", 0) or 0) - (baseline.get("lucro_liquido_real_7d", 0) or 0), 2),
                        "delta_vendas_vs_previsto": (atual.get("vendas_7d_reais", 0) or 0) - (previsto.get("vendas_projetadas", 0) or 0),
                        "delta_lucro_vs_previsto": round((atual.get("lucro_liquido_real_7d", 0) or 0) - (previsto.get("lucro_projetado", 0) or 0), 2),
                    }
                    status = "DADOS_INSUFICIENTES" if atual.get("TRAFEGO_visitas_7d", 0) in (None, 0) and atual.get("vendas_7d_reais", 0) == 0 else "AVALIADA"
                    cur.execute("""
                        INSERT INTO ia_avaliacoes_acoes
                            (id_log, id_execucao_origem, item_id, model_id, horizonte_observacao_dias,
                             data_inicio_observacao, data_fim_observacao, baseline, previsto, observado, comparacao, status)
                        VALUES (%s, %s::uuid, %s, %s, 7, %s, CURRENT_TIMESTAMP,
                                %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s)
                    """, (
                        acao["id_log"], str(acao["id_execucao_origem"]), acao["item_id"], acao["model_id"], acao["data_aplicacao"],
                        json.dumps(baseline), json.dumps(previsto), json.dumps(observado), json.dumps(comparacao), status
                    ))
                    avaliadas += 1
            conn.commit()
    except Exception as exc:
        logger.error(f"Falha ao avaliar ações maduras: {exc}")
    return avaliadas


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
# SEÇÃO 3 — MOTOR PREDITIVO (OpenAI API)
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


def configuracao_openai_valida() -> bool:
    """Valida credenciais localmente; APIs não exigem wake-up nem GPU residente."""
    if not OPENAI_API_KEY or OPENAI_API_KEY.lower().startswith("sua_chave"):
        st.error("OPENAI_API_KEY não foi configurada. Adicione a chave ao CHAVES_DADOS.env e reinicie o app.")
        return False
    if not OPENAI_MODEL_7D or not OPENAI_MODEL_30D:
        st.error("Defina OPENAI_MODEL_7D e OPENAI_MODEL_30D no CHAVES_DADOS.env.")
        return False
    return True


def resumir_memoria_para_prompt(memoria: dict | None) -> dict | None:
    """Mantém o aprendizado útil sem reenviar relatórios extensos a cada leitura de 7 dias."""
    if not isinstance(memoria, dict):
        return None
    recomendacao = memoria.get("recomendacao") or {}
    return {
        "ultima_analise_30d_em": memoria.get("ultima_analise_30d_em"),
        "qualidade_evidencia": memoria.get("qualidade_evidencia"),
        "previsoes": memoria.get("previsoes") or {},
        "decisao_anterior": {
            chave: recomendacao.get(chave)
            for chave in ("tipo_acao", "novo_preco_sugerido", "recomendacao_executiva", "cluster_mercado")
            if recomendacao.get(chave) is not None
        },
        "avaliacao_da_acao": {
            "status": memoria.get("status_ultima_avaliacao"),
            "comparacao": memoria.get("comparacao_ultima_acao") or {},
        },
    }


def compactar_lote_por_horizonte(lote_json: list[dict], horizonte: str) -> list[dict]:
    """Envia ao modelo apenas os sinais necessários ao horizonte solicitado."""
    campos_7d = {
        "model_id", "nome_variacao", "preco_atual", "custo_fabricacao_unitario",
        "vendas_7d_reais", "tendencia_vendas_WoW_perc", "lucro_liquido_real_7d",
        "trafego_visitas_7d", "trafego_conversao_perc", "abandono_carrinho_perc",
        "ads_gasto_7d", "retorno_liquido_por_ads", "taxa_cancelamento_7d_perc",
        "estoque_shopee_hoje", "LOGISTICA_capacidade_material_restante",
        "LOGISTICA_dias_estoque_restante", "previsao_deterministica_vendas_7d",
        "previsao_deterministica_lucro_7d",
        "funil_organico_impressoes", "funil_organico_cliques", "funil_organico_ctr_perc",
        "funil_ads_impressoes", "funil_ads_cliques", "funil_ads_ctr_perc",
        "funil_ads_acos_medio", "qualidade_evidencia", "limite_evidencia",
        "historico_acoes_passadas", "memoria_estrategica_30d"
    }
    resultado = []
    for produto in lote_json:
        variacoes = produto.get("variacoes_ativas", [])
        if horizonte == "7d":
            variacoes = [{k: v for k, v in variacao.items() if k in campos_7d} for variacao in variacoes]
            for variacao in variacoes:
                variacao["memoria_estrategica_30d"] = resumir_memoria_para_prompt(
                    variacao.get("memoria_estrategica_30d")
                )
        resultado.append({
            "item_id": produto.get("item_id"),
            "nome_produto": produto.get("nome_produto"),
            "horizonte_solicitado": horizonte,
            "metricas_macro_produto_30_dias": produto.get("metricas_macro_produto_30_dias", {}) if horizonte == "30d" else {},
            "variacoes_ativas": variacoes,
        })
    return resultado


def construir_prompt_otimizado(horizonte: str) -> str:
    """Prompt curto e determinístico para maximizar prefix cache e reduzir tokens."""
    base = """Você é um conselho CFO/CMO/COO para uma loja Shopee de impressão 3D sob demanda.
Analise apenas os dados JSON fornecidos. Seja matemático, específico e conciso.

REGRAS:
1. null = dado não coletado; nunca converta null em zero nem infira CTR, shadowban ou baixa descoberta.
2. CTR só existe com impressões > 0 e cliques numéricos. Correlação não prova causalidade.
3. Estoque é virtual e depende de filamento compartilhado; produto sem vendas não imobiliza estoque acabado.
4. Considere custo de fabricação, taxa Shopee aproximada de 20% + R$3 e margem mínima de segurança de 15%.
5. Sem gasto em ads, não fale em ROAS nem recomende pausar campanha. Com gasto e retorno ruim, ação de ads é apenas manual.
6. Ações permitidas: AUMENTAR_PRECO, REDUZIR_PRECO, CRIAR_PROMOCAO, CRIAR_COMBO, PAUSAR_ADS ou MANTER.
7. A previsão determinística é a âncora. Só se afaste dela quando um dado explícito justificar, explicando o motivo.
8. Retorne somente um objeto JSON válido no formato {"resultados":[...]}, com exatamente um objeto por model_id. Sem markdown ou texto externo.
"""
    if horizonte == "7d":
        return base + """
HORIZONTE: próximos 7 dias. Gere intervenção tática, reversível e objetiva.
Campos obrigatórios por objeto: item_id, model_id, tipo_acao, novo_preco_sugerido,
horas_duracao_promocao, previsao_vendas_7d, previsao_lucro_7d,
elasticidade_preco_volume, cluster_mercado, recomendacao_executiva,
relatorio_cfo_financas, relatorio_cmo_marketing, relatorio_coo_operacoes,
plano_curto_prazo_7d (máximo 3 passos) e analise_de_consequencias.
Limites: cada parecer até 240 caracteres; recomendação até 350; consequência até 300; cada passo até 180.
Não produza campos ou plano de 30 dias.
"""
    return base + """
HORIZONTE: próximos 30 dias. Use o realizado mensal como base e os 7 dias apenas como sinal recente.
Campos obrigatórios por objeto: item_id, model_id, tipo_acao, novo_preco_sugerido,
horas_duracao_promocao, previsao_vendas_7d, previsao_lucro_7d,
previsao_vendas_30d, previsao_lucro_30d, elasticidade_preco_volume,
cluster_mercado, recomendacao_executiva, relatorio_cfo_financas,
relatorio_cmo_marketing, relatorio_coo_operacoes, plano_curto_prazo_7d,
plano_longo_prazo_30d e analise_de_consequencias.
Limites: cada relatório até 500 caracteres; plano mensal até 4 passos verificáveis.
O plano mensal nunca é executável automaticamente.
"""


def extrair_array_json_resposta(texto: str) -> list[dict]:
    """Extrai a lista de resultados do JSON mode, aceitando legado em array puro."""
    def obter_resultados(carregado) -> list[dict] | None:
        if isinstance(carregado, list):
            return carregado
        if isinstance(carregado, dict) and isinstance(carregado.get("resultados"), list):
            return carregado["resultados"]
        return None

    limpo = texto.replace("```json", "").replace("```", "").strip()
    try:
        carregado = json.loads(limpo)
        resultados = obter_resultados(carregado)
        if resultados is not None:
            return resultados
    except json.JSONDecodeError:
        pass
    inicios = [pos for pos in (limpo.find("["), limpo.find("{")) if pos >= 0]
    if not inicios:
        raise ValueError("A resposta não contém JSON estruturado.")
    inicio = min(inicios)
    carregado, _ = json.JSONDecoder().raw_decode(limpo[inicio:])
    resultados = obter_resultados(carregado)
    if resultados is None:
        raise ValueError("A resposta JSON não contém a lista 'resultados'.")
    return resultados


def gerar_fallback_lote(lote_json: list[dict], horizonte: str, motivo: str) -> list[dict]:
    """Mantém a auditoria utilizável quando o endpoint falha, sem inventar análise."""
    resultados = []
    for produto in lote_json:
        for variacao in produto.get("variacoes_ativas", []):
            preco = float(variacao.get("preco_atual") or 0)
            resultados.append({
                "item_id": produto.get("item_id"),
                "model_id": variacao.get("model_id"),
                "tipo_acao": "MANTER",
                "novo_preco_sugerido": preco,
                "horas_duracao_promocao": 0,
                "previsao_vendas_7d": variacao.get("previsao_deterministica_vendas_7d", 0),
                "previsao_lucro_7d": variacao.get("previsao_deterministica_lucro_7d", 0.0),
                "previsao_vendas_30d": variacao.get("previsao_deterministica_vendas_30d", 0),
                "previsao_lucro_30d": variacao.get("previsao_deterministica_lucro_30d", 0.0),
                "plano_curto_prazo_7d": ["Repetir a análise quando o endpoint de IA estiver disponível."],
                "plano_longo_prazo_30d": [] if horizonte == "7d" else ["Preservar a estratégia atual até nova análise completa."],
                "elasticidade_preco_volume": variacao.get("elasticidade_preco_volume", 0),
                "cluster_mercado": "Análise indisponível",
                "recomendacao_executiva": "Nenhuma mudança automática foi recomendada porque a análise externa não foi concluída.",
                "analise_de_consequencias": motivo,
                "falha_modelo_externo": True,
            })
    return resultados


def normalizar_saida_modelo(recomendacao: dict, dados: dict) -> dict:
    """Normaliza tipos e ações antes que qualquer saída do LLM alcance interface ou API."""
    resultado = dict(recomendacao)
    alertas = []

    def numero_finito(valor, padrao: float) -> float:
        try:
            convertido = float(valor)
            return convertido if math.isfinite(convertido) else float(padrao)
        except (TypeError, ValueError):
            return float(padrao)

    acoes_validas = {
        "AUMENTAR_PRECO", "REDUZIR_PRECO", "CRIAR_PROMOCAO",
        "CRIAR_COMBO", "PAUSAR_ADS", "MANTER",
    }
    acao = str(resultado.get("tipo_acao") or "MANTER").strip().upper()
    if acao not in acoes_validas:
        alertas.append(f"Ação desconhecida '{acao}' substituída por MANTER.")
        acao = "MANTER"
    resultado["tipo_acao"] = acao

    preco_atual = numero_finito(dados.get("preco_atual"), 0)
    novo_preco = numero_finito(resultado.get("novo_preco_sugerido"), preco_atual)
    if novo_preco <= 0:
        alertas.append("Preço inválido substituído pelo preço atual.")
        novo_preco = preco_atual
    resultado["novo_preco_sugerido"] = round(novo_preco, 2)

    for campo, padrao in (
        ("previsao_vendas_7d", dados.get("previsao_vendas_7d", 0)),
        ("previsao_vendas_30d", dados.get("previsao_vendas_30d", 0)),
    ):
        resultado[campo] = max(0, int(round(numero_finito(resultado.get(campo), padrao))))
    for campo, padrao in (
        ("previsao_lucro_7d", dados.get("previsao_lucro_7d", 0)),
        ("previsao_lucro_30d", dados.get("previsao_lucro_30d", 0)),
        ("elasticidade_preco_volume", dados.get("elasticidade_preco_volume", 0)),
    ):
        resultado[campo] = round(numero_finito(resultado.get(campo), padrao), 4)

    duracao = int(round(numero_finito(resultado.get("horas_duracao_promocao"), 0)))
    resultado["horas_duracao_promocao"] = max(0, min(168, duracao))

    for campo in ("plano_curto_prazo_7d", "plano_longo_prazo_30d", "plano_acao_shopee"):
        valor = resultado.get(campo, [])
        if isinstance(valor, str):
            valor = [valor]
        elif not isinstance(valor, list):
            valor = []
        resultado[campo] = [str(item)[:500] for item in valor if item is not None][:6]

    for campo in (
        "cluster_mercado", "recomendacao_executiva", "analise_de_consequencias",
        "relatorio_cfo_financas", "relatorio_cmo_marketing", "relatorio_coo_operacoes",
    ):
        valor = resultado.get(campo)
        if valor is not None:
            resultado[campo] = str(valor)[:2000]

    resultado["falha_modelo_externo"] = False
    if alertas:
        resultado["alerta_validacao_modelo"] = " ".join(alertas)
    return resultado


def chamar_cerebro_openai_preditivo(lote_json: list[dict], horizonte: str = "7d", max_tentativas: int = 2) -> list[dict]:
    """Executa a análise via API OpenAI com JSON mode, sem dependência de GPU remota."""
    import time

    if horizonte not in {"7d", "30d"}:
        raise ValueError("Horizonte de auditoria inválido. Use '7d' ou '30d'.")

    modelo = OPENAI_MODEL_7D if horizonte == "7d" else OPENAI_MODEL_30D
    esforco_raciocinio = OPENAI_REASONING_7D if horizonte == "7d" else OPENAI_REASONING_30D
    timeout_request = 180 if horizonte == "7d" else 300

    lote_compacto = compactar_lote_por_horizonte(lote_json, horizonte)
    total_variacoes = sum(len(p.get("variacoes_ativas", [])) for p in lote_compacto)
    max_tokens = (
        min(3200, 450 + 550 * total_variacoes)
        if horizonte == "7d"
        else min(3600, 600 + 1400 * total_variacoes)
    )
    prompt_sistema = construir_prompt_otimizado(horizonte)
    auditoria_json = json.dumps(lote_compacto, ensure_ascii=False, separators=(",", ":"), default=str)

    payload = {
        "model": modelo,
        "messages": [
            {"role": "system", "content": prompt_sistema},
            {"role": "user", "content": f"Auditoria:{auditoria_json}"},
        ],
        "max_completion_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    if esforco_raciocinio in {"low", "medium", "high"}:
        payload["reasoning_effort"] = esforco_raciocinio
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    tentativas_executadas = 0
    fallback_sem_reasoning = False
    for tentativa in range(1, max_tentativas + 1):
        tentativas_executadas = tentativa
        try:
            logger.info(
                f"🧠 [OPENAI:{modelo}] Processando {total_variacoes} SKU(s) em {len(lote_json)} produto(s) "
                f"(tentativa {tentativa}/{max_tentativas})..."
            )

            response = HTTP_SESSION.post(
                OPENAI_CHAT_COMPLETIONS_URL,
                headers=headers,
                json=payload,
                timeout=(10, timeout_request),
            )
            if response.status_code == 400 and "reasoning_effort" in payload and not fallback_sem_reasoning:
                logger.warning("A API rejeitou reasoning_effort; repetindo uma única vez sem esse parâmetro.")
                payload.pop("reasoning_effort", None)
                fallback_sem_reasoning = True
                continue
            if response.status_code in {401, 403}:
                logger.error("🔴 [OPENAI] Credencial inválida ou sem permissão para o modelo configurado.")
                break
            if response.status_code == 429:
                try:
                    espera = int(response.headers.get("Retry-After", "3") or 3)
                except (TypeError, ValueError):
                    espera = 3
                espera = min(15, max(1, espera))
                logger.warning(f"🟠 [OPENAI] Limite temporário atingido; aguardando {espera}s.")
                time.sleep(espera)
                continue
            if 400 <= response.status_code < 500:
                logger.error(
                    f"🔴 [OPENAI] Requisição rejeitada ({response.status_code}): "
                    f"{response.text[:300]}"
                )
                break
            response.raise_for_status()

            corpo_resposta = response.json()
            texto = corpo_resposta["choices"][0]["message"]["content"].strip()
            resultado = extrair_array_json_resposta(texto)
            chaves_esperadas = {
                (int(p["item_id"]), int(v["model_id"]))
                for p in lote_json for v in p.get("variacoes_ativas", [])
                if p.get("item_id") is not None and v.get("model_id") is not None
            }
            chaves_recebidas = {
                (int(r["item_id"]), int(r["model_id"]))
                for r in resultado
                if isinstance(r, dict) and r.get("item_id") is not None and r.get("model_id") is not None
            }
            if chaves_recebidas != chaves_esperadas or len(resultado) != len(chaves_esperadas):
                raise ValueError(
                    f"Resposta incompleta: esperados {len(chaves_esperadas)} SKUs, "
                    f"recebidos {len(chaves_recebidas)} pares válidos de produto/SKU."
                )
            uso = corpo_resposta.get("usage") or {}
            logger.success(
                f"✅ [OPENAI:{modelo}] Lote concluído. "
                f"Tokens entrada/saída: {uso.get('prompt_tokens', 'n/d')}/{uso.get('completion_tokens', 'n/d')}."
            )
            return resultado

        except requests.exceptions.Timeout as e:
            logger.error(f"🔴 [OPENAI] Timeout na tentativa {tentativa}; não haverá reenvio ambíguo para evitar custo duplicado.")
            break

        except requests.exceptions.RequestException as e:
            logger.error(f"🔴 [OPENAI] Falha de rede na tentativa {tentativa}: {e}")

        except json.JSONDecodeError as e:
            logger.error(f"🔴 [OPENAI] IA retornou JSON inválido na tentativa {tentativa}: {e}")

        except Exception as e:
            logger.error(f"🔴 [OPENAI] Erro inesperado na tentativa {tentativa}: {e}")

        if tentativa < max_tentativas:
            logger.info("⏳ Aguardando 5 segundos antes de tentar novamente...")
            time.sleep(5)

    mensagem_critica = f"A IA externa não concluiu o lote após {tentativas_executadas} tentativa(s)."
    logger.error(mensagem_critica)
    return gerar_fallback_lote(lote_json, horizonte, mensagem_critica)


def processar_em_lotes(
    dossie_completo: list[dict], horizonte: str, ao_concluir_lote=None,
) -> list[dict]:
    """Processa um único horizonte por vez para evitar competição de contexto na GPU."""
    if horizonte not in {"7d", "30d"}:
        raise ValueError("Horizonte de auditoria inválido. Use '7d' ou '30d'.")
    max_vars_por_lote = 5 if horizonte == "7d" else 2
    originais_por_chave = {
        (int(d["item_id"]), int(d["model_id"])): d
        for d in dossie_completo
        if d.get("item_id") is not None and d.get("model_id") is not None
    }
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
                    "dias_trafego_coletados_30d": var.get("COBERTURA_dias_trafego_30d", 0),
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
            "cobertura_dias_trafego_30d": var.get("COBERTURA_dias_trafego_30d", 0),
            "cobertura_dias_com_venda_30d": var.get("COBERTURA_dias_com_venda_30d", 0),
            "tendencia_vendas_WoW_perc": var.get("tendencia_vendas_WoW_perc", 0),
            "ritmo_7d_vs_30d_perc": var.get("ritmo_7d_vs_30d_perc", 0),
            "lucro_liquido_real_7d": var["lucro_liquido_real_7d"],
            "lucro_liquido_real_30d": var.get("lucro_liquido_real_30d", 0),

            # --- INJEÇÃO DE DADOS PARA A IA (Com blindagem para Nulos) ---
            "funil_organico_impressoes": var.get("TRAFEGO_ORG_impressoes_7d"),
            "funil_organico_cliques": var.get("TRAFEGO_ORG_cliques_7d"),
            "funil_organico_ctr_perc": var.get("TRAFEGO_ORG_ctr_perc"),
            "funil_organico_rejeicao_perc": var.get("TRAFEGO_ORG_taxa_rejeicao_perc"),
            "funil_organico_impressoes_30d": var.get("TRAFEGO_ORG_impressoes_30d"),
            "funil_organico_cliques_30d": var.get("TRAFEGO_ORG_cliques_30d"),
            "funil_organico_ctr_30d_perc": var.get("TRAFEGO_ORG_ctr_30d_perc"),
            "funil_ads_impressoes": var.get("ADS_impressoes_7d"),
            "funil_ads_cliques": var.get("ADS_cliques_7d"),
            "funil_ads_ctr_perc": var.get("ADS_ctr_perc"),
            "funil_ads_acos_medio": var.get("ADS_acos_medio"),
            "funil_ads_impressoes_30d": var.get("ADS_impressoes_30d"),
            "funil_ads_cliques_30d": var.get("ADS_cliques_30d"),
            "funil_ads_ctr_30d_perc": var.get("ADS_ctr_30d_perc"),
            "funil_ads_gmv_30d": var.get("ADS_gmv_30d"),
            # --------------------------------------------------------------

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
            "previsao_deterministica_lucro_7d": var.get("previsao_lucro_7d", 0),
            "previsao_deterministica_vendas_30d": var.get("previsao_vendas_30d", 0),
            "previsao_deterministica_lucro_30d": var.get("previsao_lucro_30d", 0),
            "qualidade_evidencia": classificar_confianca_evidencia(var)[0],
            "limite_evidencia": classificar_confianca_evidencia(var)[1],
            "historico_acoes_passadas": var["historico_acoes_passadas"],
            "memoria_estrategica_30d": var.get("MEMORIA_ESTRATEGICA_30D"),
        })

    # 2. O GATEKEEPER: Separar os Vivos dos Fantasmas
    produtos_ativos = []
    resultados_finais = []

    for p in produtos_agrupados.values():
        macro = p["metricas_macro_produto_30_dias"]
        vendas_totais_30d = sum(v["vendas_30d_reais"] for v in p["variacoes_ativas"])
        topo_mensuravel = any(
            v.get("funil_organico_impressoes_30d") is not None
            for v in p["variacoes_ativas"]
        )
        cobertura_trafego = int(macro.get("dias_trafego_coletados_30d", 0) or 0)
        evidencia_descoberta = cobertura_trafego >= 7 or topo_mensuravel

        if (
            evidencia_descoberta
            and macro["visitas_totais_30d"] <= 10
            and macro["gasto_ads_total_30d"] == 0
            and vendas_totais_30d == 0
        ):
            # Processamento GRATUITO e INSTANTÂNEO
            for var in p["variacoes_ativas"]:
                original = originais_por_chave.get((int(p["item_id"]), int(var["model_id"])))
                if original:
                    rec_fantasma = {
                        "item_id": p["item_id"],
                        "model_id": var["model_id"],
                        "tipo_acao": "MANTER",
                        "novo_preco_sugerido": var["preco_atual"],
                        "previsao_vendas_7d": 0,
                        "previsao_lucro_7d": 0.0,
                        "previsao_vendas_30d": 0,
                        "previsao_lucro_30d": 0.0,
                        "plano_curto_prazo_7d": ["Validar título, atributos e imagem de capa antes de investir em mídia."],
                        "plano_longo_prazo_30d": ["Reavaliar descoberta após 30 dias com dados de impressões e cliques, se disponíveis."],
                        "elasticidade_preco_volume": 0.0,
                        "cluster_mercado": "Baixa atividade observada",
                        "recomendacao_executiva": "Há pouca atividade observada com cobertura suficiente; valide descoberta e atratividade antes de alterar preço.",
                        "relatorio_cfo_financas": "Sem vendas observadas; não há evidência suficiente para atribuir o resultado ao preço.",
                        "relatorio_cmo_marketing": (
                            f"Foram observadas {macro['visitas_totais_30d']} visitas em "
                            f"{cobertura_trafego or 30} dia(s) de referência. "
                            + ("O topo do funil está mensurado." if topo_mensuravel else "Impressões/cliques estão indisponíveis; não foi inferido CTR.")
                        ),
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

    if resultados_finais and ao_concluir_lote:
        ao_concluir_lote(list(resultados_finais))

    # 3. SMART BATCHING: Fatiamento de Variações
    lotes = []
    lote_atual = []
    variacoes_no_lote = 0
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
            if lote_atual and variacoes_no_lote + len(chunk_vars) > max_vars_por_lote:
                lotes.append(lote_atual)
                lote_atual = []
                variacoes_no_lote = 0
            lote_atual.append(p_chunk)
            variacoes_no_lote += len(chunk_vars)
    if lote_atual:
        lotes.append(lote_atual)

    if lotes:
        barra = st.progress(0, text="🚀 Iniciando auditoria C-Level por API OpenAI...")
        lotes_concluidos = 0

        # Uma única requisição por vez evita competição por KV cache na GPU única.
        # O lote pequeno explora o modelo 72B sem repetir o contexto após timeout.
        for lote in lotes:
            resultados_do_lote = []
            try:
                resultado_lote = chamar_cerebro_openai_preditivo(lote, horizonte)
                for rec in resultado_lote:
                    try:
                        rec_item_id = int(rec.get("item_id"))
                        rec_model_id = int(rec.get("model_id"))
                    except (TypeError, ValueError):
                        continue

                    original = originais_por_chave.get((rec_item_id, rec_model_id))
                    if not original:
                        continue

                    rec = normalizar_saida_modelo(rec, original)
                    rec["item_id"] = rec_item_id
                    rec["model_id"] = rec_model_id
                    rec["horizonte_auditoria"] = horizonte
                    rec["dados_atuais"] = original
                    rec["score_urgencia"] = calcular_score_urgencia(original)
                    rec["dias_estoque"] = calcular_dias_estoque(original)

                    preco_original = float(original.get("preco_atual", 0) or 0)
                    if rec.get("novo_preco_sugerido") is None:
                        rec["novo_preco_sugerido"] = preco_original

                    rec.setdefault("previsao_vendas_7d", original.get("previsao_vendas_7d", 0))
                    rec.setdefault("previsao_lucro_7d", original.get("previsao_lucro_7d", 0))
                    rec.setdefault("previsao_vendas_30d", original.get("previsao_vendas_30d", 0))
                    rec.setdefault("previsao_lucro_30d", original.get("previsao_lucro_30d", 0))
                    rec.setdefault("plano_curto_prazo_7d", [])
                    rec.setdefault("plano_longo_prazo_30d", [])
                    rec.setdefault("elasticidade_preco_volume", original.get("elasticidade_preco_volume", 0))
                    rec.setdefault("cluster_mercado", original.get("cluster_mercado", "Estável"))
                    rec.setdefault("recomendacao_executiva", original.get("recomendacao_executiva", "Monitorar"))
                    resultados_finais.append(rec)
                    resultados_do_lote.append(rec)
            except Exception as e:
                logger.error(f"Erro ao processar lote: {e}")
                raise

            if resultados_do_lote and ao_concluir_lote:
                ao_concluir_lote(resultados_do_lote)

            lotes_concluidos += 1
            barra.progress(
                lotes_concluidos / len(lotes),
                text=f"⏳ Conselho auditando {lotes_concluidos}/{len(lotes)} submódulos ativos..."
            )

        barra.empty()

    return resultados_finais


# ==============================================================================
# ORQUESTRAÇÃO DOS HORIZONTES
# ==============================================================================
def executar_auditoria_por_horizonte(horizonte: str, status_boot) -> list[dict]:
    """Executa e persiste um único horizonte; 7d é recorrente, 30d é estratégico."""
    if horizonte not in {"7d", "30d"}:
        raise ValueError("Horizonte de auditoria inválido. Use '7d' ou '30d'.")

    status_boot.write("Lendo Data Warehouse e consolidando métricas...")
    dossie = gerar_dossie_produtos_com_memoria()
    if not dossie:
        status_boot.update(label="Sem produtos ativos para auditar", state="error", expanded=True)
        st.stop()

    acoes_avaliadas = avaliar_acoes_maduras(dossie)
    if acoes_avaliadas:
        status_boot.write(f"Atualizando aprendizagem com {acoes_avaliadas} ação(ões) já maturadas...")
        dossie = enriquecer_dossie_com_memoria(dossie)

    descricao = "operacional de 7 dias" if horizonte == "7d" else "estratégica de 30 dias"
    cobertura_inicial = {
        "variacoes_esperadas": len(dossie),
        "dias_trafego_30d_mediana": int(pd.Series([
            d.get("COBERTURA_dias_trafego_30d", 0) for d in dossie
        ]).median() or 0),
    }
    id_checkpoint, _ = iniciar_ou_retomar_checkpoint(
        horizonte, len(dossie), cobertura_inicial,
    )

    retomados, dossie_a_verificar = (
        separar_resultados_do_checkpoint(id_checkpoint, horizonte, dossie)
        if id_checkpoint else ([], dossie)
    )
    reutilizados, pendentes = separar_resultados_reutilizaveis(horizonte, dossie_a_verificar)
    resultados_iniciais = retomados + reutilizados

    if id_checkpoint and resultados_iniciais:
        persistir_lote_no_checkpoint(id_checkpoint, horizonte, resultados_iniciais)
    if retomados:
        status_boot.write(
            f"Retomada segura: {len(retomados)} variação(ões) já concluídas foram restauradas do checkpoint."
        )
    if reutilizados:
        status_boot.write(
            f"Economia de inferência: {len(reutilizados)} variação(ões) sem mudança reutilizadas com segurança."
        )

    novos_resultados = []
    if pendentes:
        status_boot.write(
            f"Enviando somente {len(pendentes)} de {len(dossie)} variações para análise {descricao}..."
        )
        if not configuracao_openai_valida():
            status_boot.update(label="Configuração OpenAI pendente", state="error", expanded=True)
            st.stop()

        def confirmar_lote(lote: list[dict]) -> None:
            if id_checkpoint and not persistir_lote_no_checkpoint(id_checkpoint, horizonte, lote):
                raise RuntimeError("Falha ao confirmar o lote no checkpoint; a execução poderá ser retomada.")

        novos_resultados = processar_em_lotes(
            pendentes,
            horizonte=horizonte,
            ao_concluir_lote=confirmar_lote if id_checkpoint else None,
        )
    else:
        status_boot.write("Nenhum fato mudou; nenhuma chamada à OpenAI foi necessária.")

    resultados = resultados_iniciais + novos_resultados
    resultados.sort(key=lambda r: int(r.get("score_urgencia", 0) or 0), reverse=True)
    for resultado in resultados:
        resultado["horizonte_auditoria"] = horizonte

    if id_checkpoint:
        finalizar_checkpoint(id_checkpoint, horizonte, resultados, len(dossie))
        id_execucao = id_checkpoint
    else:
        id_execucao = persistir_auditoria_analitica(horizonte, resultados)
    if id_execucao:
        st.session_state.id_execucao_analitica = id_execucao
        for resultado in resultados:
            resultado["id_execucao_analitica"] = id_execucao

    destino = CACHE_AUDITORIA_7D if horizonte == "7d" else CACHE_AUDITORIA_30D
    with open(destino, "w", encoding="utf-8") as arquivo:
        json.dump(resultados, arquivo, ensure_ascii=False, indent=4)
    # Mantém o arquivo legado atualizado para não quebrar instalações existentes.
    with open(CACHE_AUDITORIA, "w", encoding="utf-8") as arquivo:
        json.dump(resultados, arquivo, ensure_ascii=False, indent=4)
    return resultados


def executar_analise_7_dias(status_boot) -> list[dict]:
    """Fluxo recorrente: decisão operacional baseada exclusivamente nos sinais de 7 dias."""
    return executar_auditoria_por_horizonte("7d", status_boot)


def executar_analise_30_dias(status_boot) -> list[dict]:
    """Fluxo estratégico: diagnóstico mensal completo para a primeira execução e revisões ocasionais."""
    return executar_auditoria_por_horizonte("30d", status_boot)


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
    id_execucao_origem = st.session_state.get("id_execucao_analitica")
    with get_connection() as conn:
        with conn.cursor() as cur:
            if id_execucao_origem:
                cur.execute(
                    """
                    INSERT INTO log_acoes_shopee
                        (item_id, model_id, tipo_acao, detalhe_acao, impacto_projetado, status_api, id_execucao_origem)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::uuid)
                    """,
                    (item_id, model_id, tipo_acao, detalhe, json.dumps(impacto_json), status, id_execucao_origem),
                )
            else:
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
    cobertura_trafego = int(dados.get("COBERTURA_dias_trafego_30d", 0) or 0)
    cobertura_vendas = int(dados.get("COBERTURA_dias_com_venda_30d", 0) or 0)
    preco_mudou = abs(float(dados.get("preco_tendencia_7d_perc", 0) or 0)) >= 0.5

    if vendas_30d >= 20 and visitas_30d >= 100 and vendas_7d > 0 and cobertura_trafego >= 21 and cobertura_vendas >= 7:
        return "Alta", "Volume e cobertura consistentes no período de 30 dias", "success"
    if vendas_30d >= 5 or visitas_30d >= 30:
        cobertura = f"Cobertura: {cobertura_trafego}/30 dias de tráfego, {cobertura_vendas}/30 dias com vendas"
        detalhe = f"Amostra moderada; valide antes de escalar. {cobertura}"
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
    st.session_state.horizonte_auditoria = None
    
    # 1. Definimos os caches e seus horizontes
    caches_disponiveis = [
        (CACHE_AUDITORIA_7D, "7d"),
        (CACHE_AUDITORIA_30D, "30d"),
        (CACHE_AUDITORIA, None)
    ]
    
    # 2. Filtramos apenas os que existem fisicamente no disco
    caches_existentes = [c for c in caches_disponiveis if c[0].exists()]
    
    # 3. Ordenamos do mais recente (modificado há menos tempo) para o mais antigo
    caches_ordenados = sorted(caches_existentes, key=lambda x: os.path.getmtime(x[0]), reverse=True)

    for cache, horizonte in caches_ordenados:
        try:
            with open(cache, "r", encoding="utf-8") as f:
                st.session_state.analises_preditivas = json.load(f)
            
            st.session_state.horizonte_auditoria = horizonte or (
                st.session_state.analises_preditivas[0].get("horizonte_auditoria")
                if st.session_state.analises_preditivas else None
            )
            
            if st.session_state.analises_preditivas:
                st.session_state.id_execucao_analitica = st.session_state.analises_preditivas[0].get("id_execucao_analitica")
            
            # Interrompe no primeiro (que é o mais recente)
            break
        except Exception:
            continue

# ─── Barra Lateral (Sidebar) para o Disparo ──────────────────────────────────
with st.container(border=True):
    st.subheader("Atualizar diagnóstico")
    st.caption("A análise de 7 dias é operacional e deve ser usada no dia a dia. A análise de 30 dias é estratégica, mais completa e indicada na primeira execução ou após longo período sem revisão.")
    botao_7d, botao_30d = st.columns(2)
    executar_7d = botao_7d.button("Atualizar análise operacional · 7 dias", type="primary", use_container_width=True, help="Envia somente os sinais recentes ao modelo. É o fluxo recomendado para uso recorrente.")
    executar_30d = botao_30d.button("Executar diagnóstico estratégico · 30 dias", use_container_width=True, help="Envia o dossiê mensal completo. Use na primeira execução e em revisões estratégicas.")

    horizonte_escolhido = "7d" if executar_7d else "30d" if executar_30d else None
    if horizonte_escolhido:
        titulo = "análise operacional de 7 dias" if horizonte_escolhido == "7d" else "diagnóstico estratégico de 30 dias"
        with st.status(f"Iniciando {titulo}...", expanded=True) as status_boot:
            resultados_ia = executar_analise_7_dias(status_boot) if horizonte_escolhido == "7d" else executar_analise_30_dias(status_boot)
            st.session_state.analises_preditivas = resultados_ia
            st.session_state.horizonte_auditoria = horizonte_escolhido
            status_boot.update(label=f"{titulo.capitalize()} concluído!", state="complete", expanded=False)
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
    
    # 1. Recuperação dos Dados Globais (Sem sofrer cortes dos filtros do ecrã)
    analises_globais = st.session_state.analises_preditivas
    df_globais = pd.DataFrame(analises_globais)
    if 'dados_atuais' in df_globais.columns:
        dados_globais_expandidos = df_globais['dados_atuais'].apply(lambda x: pd.Series(x if isinstance(x, dict) else {}))
        df_globais = pd.concat([df_globais.drop(columns=['dados_atuais']), dados_globais_expandidos], axis=1)
        df_globais = df_globais.loc[:, ~df_globais.columns.duplicated(keep='last')]
        
    # 2. Cálculos GLOBAIS da Loja (Remove duplicados de variação para somar Ads do anúncio pai corretamente)
    if 'item_id' in df_globais.columns and 'ADS_gasto_7d_total_anuncio' in df_globais.columns:
        df_unicos_por_anuncio = df_globais.drop_duplicates(subset=['item_id'])
        total_gasto_loja = _serie_numerica(df_unicos_por_anuncio, 'ADS_gasto_7d_total_anuncio').sum()
    else:
        total_gasto_loja = _serie_numerica(df_globais, 'ADS_gasto_7d').sum()

    total_lucro_loja = _serie_numerica(df_globais, 'lucro_liquido_real_7d').sum()
    total_vendas_loja = _serie_numerica(df_globais, 'vendas_7d_reais').sum()
    total_visitas_loja = _serie_numerica(df_globais, 'visitas_7d').sum()
    total_carrinhos_loja = _serie_numerica(df_globais, 'carrinhos_7d').sum()
    total_pedidos_loja = _serie_numerica(df_globais, 'PEDIDOS_7d').sum()
    total_cancelamentos_loja = _serie_numerica(df_globais, 'cancelamentos_7d').sum()
    
    conversao_loja = (total_vendas_loja / total_visitas_loja * 100) if total_visitas_loja else 0
    abandono_loja = ((total_carrinhos_loja - total_vendas_loja) / total_carrinhos_loja * 100) if total_carrinhos_loja else 0
    cancelamento_loja = (total_cancelamentos_loja / total_pedidos_loja * 100) if total_pedidos_loja else 0
    
    st.subheader("🌐 Visão Global da Loja (Últimos 7 dias)")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Resultado Operacional (Loja)", f"R$ {total_lucro_loja:,.2f}", help="Soma do resultado de todos os SKUs processados na auditoria, não apenas os visíveis.")
    k2.metric("Conversão Global", f"{conversao_loja:.2f}%" if total_visitas_loja else "Sem dado")
    k3.metric("Gasto Total em Ads", f"R$ {total_gasto_loja:,.2f}", help="Soma bruta do gasto dos anúncios originais na Shopee, corrigindo rateios fracionados por SKU.")
    k4.metric("Cancelamento Global", f"{cancelamento_loja:.1f}%" if total_pedidos_loja else "Sem dado")
    
    st.divider()
    
    # 3. Cálculos do Recorte Filtrado (Os SKUs que estão a ser exibidos neste momento)
    st.subheader("🎯 Recorte Operacional (Métricas dos SKUs filtrados)")
    lucro_visivel = _serie_numerica(df_analises, 'lucro_liquido_real_7d').sum()
    vendas_visiveis = _serie_numerica(df_analises, 'vendas_7d_reais').sum()
    gasto_visivel = _serie_numerica(df_analises, 'ADS_gasto_7d').sum()
    produtos_criticos = sum(1 for a in analises_globais if a.get("score_urgencia", 0) >= 40)
    dias_min_estoque  = min((a.get("dias_estoque", 999) for a in analises_globais if a.get("dias_estoque", 999) < 999), default=999)
    
    with st.container(border=True):
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("💰 Lucro (Filtro)", f"R$ {lucro_visivel:,.2f}")
        c2.metric("📦 Vendas (Filtro)", f"{int(vendas_visiveis)} un.")
        c3.metric("📣 Ads Rateado (Filtro)", f"R$ {gasto_visivel:,.2f}", help="Fração dos custos correspondente APENAS aos SKUs exibidos no momento sob ação.")
        c4.metric("🚨 Críticos (Global)", f"{produtos_criticos}", delta=f"de {len(analises_globais)} avaliados", delta_color="inverse")
        c5.metric("⏳ Autonomia Mínima", f"{dias_min_estoque if dias_min_estoque < 999 else '∞'} dias", delta_color="inverse" if dias_min_estoque < 14 else "normal")
    
    evidencias_resumo = df_analises['confianca'].value_counts()
    st.caption(f"Evidência dos {len(df_analises)} SKUs filtrados: {evidencias_resumo.get('Alta', 0)} alta, {evidencias_resumo.get('Moderada', 0)} moderada, {evidencias_resumo.get('Baixa', 0)} baixa. Abandono de carrinho observado (global): {abandono_loja:.1f}%")

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

def salvar_cache_auditoria():
    destino = CACHE_AUDITORIA_7D if st.session_state.get("horizonte_auditoria", "7d") == "7d" else CACHE_AUDITORIA_30D
    try:
        with open(destino, "w", encoding="utf-8") as f:
            json.dump(st.session_state.analises_preditivas, f, ensure_ascii=False, indent=4)
        with open(CACHE_AUDITORIA, "w", encoding="utf-8") as f:
            json.dump(st.session_state.analises_preditivas, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Falha ao persistir cache de auditoria: {e}")


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

        # 1. Limpeza do Nome do Produto no Cabeçalho
        nome_produto_limpo = padronizar_texto(p['nome_produto'])

        with st.expander(f"⚡ {nome_produto_limpo} | {p['acoes_pendentes']} SKUs exigem ação | {badge}", expanded=(score >= 40)):
            var_base = p["variacoes"][0]

            with st.container(border=True):
                # 2. Limpeza dos Pareceres da IA
                motivo_limpo = padronizar_texto(var_base.get('recomendacao_executiva', ''))
                consequencia_limpa = padronizar_texto(var_base.get('analise_de_consequencias', ''))
                
                st.markdown(f"**🎯 Motivo da Intervenção:** {motivo_limpo}")
                st.caption(f"**Projeção IA:** {consequencia_limpa}")

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
                
                # 3. Limpeza do Nome da Variação e Evidência
                nome_variacao_limpo = padronizar_texto(dados_var.get('nome_variacao', 'SKU'))
                evidencia_limpa = padronizar_texto(leitura_evidencia)

                with st.container(border=True):
                    st.markdown(f"### {rotulo_acao(acao_var)} · {nome_variacao_limpo}")
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
                        st.caption(f"Evidência: **{confianca}** — {evidencia_limpa}")
                        st.caption("A projeção é uma hipótese. Confira a justificativa e a consequência abaixo antes de confirmar.")
                    
                    with st.expander("Plano por horizonte: 7 dias e 30 dias"):
                        plano_7d, plano_30d = st.columns(2)
                        with plano_7d:
                            st.markdown("**Curto prazo · 7 dias**")
                            # 4. Limpeza dos Passos do Plano
                            for passo in analise_var.get("plano_curto_prazo_7d", []):
                                st.write(f"• {padronizar_texto(passo)}")
                            st.caption(f"Cenário: {int(analise_var.get('previsao_vendas_7d', 0) or 0)} un. | R$ {float(analise_var.get('previsao_lucro_7d', 0) or 0):.2f}")
                        
                        with plano_30d:
                            st.markdown("**Longo prazo · 30 dias**")
                            # 4. Limpeza dos Passos do Plano
                            for passo in analise_var.get("plano_longo_prazo_30d", []):
                                st.write(f"• {padronizar_texto(passo)}")
                            st.caption(f"Cenário: {int(analise_var.get('previsao_vendas_30d', 0) or 0)} un. | R$ {float(analise_var.get('previsao_lucro_30d', 0) or 0):.2f}")
                        st.info("O plano de 30 dias é estratégico e não dispara nenhuma alteração automática.")
                    
                    st.divider()
                    col_info, col_btn = st.columns([6, 4], vertical_alignment="center")

                    with col_info:
                        if confianca == "Baixa":
                            st.warning(f"Evidência baixa — não automatize sem teste controlado. {evidencia_limpa}")
                        else:
                            st.caption(f"Evidência {confianca.lower()}: {evidencia_limpa}")
                        st.markdown(f"**SKU:** `{nome_variacao_limpo}`")
                        st.caption(f"**Ação Definida:** {acao_var}")
                        if modo_execucao == "RECOMENDAR":
                            st.info("📌 Alteração Manual Necessária no Seller Center", icon="ℹ️")

                    with col_btn:
                        # 1. VERIFICAÇÃO DE ESTADO LOCAL (Resistente ao F5)
                        status_local = analise_var.get("status_api_execucao")

                        if status_local == "SUCESSO":
                            st.success("✅ Confirmado ativo na Shopee", icon="🟢")
                            col_done, col_reverify = st.columns([3, 1])
                            with col_done:
                                st.button("Ação Concluída", key=f"done_{dados_var['model_id']}", disabled=True, use_container_width=True)
                            reverify_key = f"reverify_open_{dados_var['model_id']}"

                            with col_reverify:
                                if st.button("🔄", key=f"reverify_{dados_var['model_id']}", help="Reverificar na Shopee", use_container_width=True):
                                    st.session_state[reverify_key] = True
                                    st.rerun()

                            if st.session_state.get(reverify_key, False):
                                discount_id = analise_var.get("discount_id_shopee")

                                if not discount_id:
                                    # Item marcado SUCESSO por execução antiga, sem discount_id salvo — não dá pra auto-checar
                                    st.warning("Este item foi marcado como concluído antes da verificação automática existir. "
                                                "Confira manualmente no Seller Center. Se não estiver lá, use 'Liberar mesmo assim' abaixo.")
                                    if st.button("Liberar para nova tentativa", key=f"forcerelease_{dados_var['model_id']}"):
                                        analise_var["status_api_execucao"] = None
                                        st.session_state[reverify_key] = False
                                        salvar_cache_auditoria()
                                        st.rerun()
                                else:
                                    status_api, detalhe = verificar_status_promocao(discount_id)
                                    if status_api in ("ongoing", "upcoming"):
                                        st.toast(f"Confirmado: {detalhe}", icon="✅")
                                    elif status_api == "rejeitado":
                                        analise_var["status_api_execucao"] = None
                                        analise_var.pop("discount_id_shopee", None)
                                        salvar_cache_auditoria()
                                        st.toast("Não estava realmente ativo — liberado para nova tentativa.", icon="🔓")
                                    else:
                                        st.toast(f"Status ainda incerto ({status_api}). Tente de novo em instantes.", icon="❓")
                                    st.session_state[reverify_key] = False
                                    st.rerun()

                        elif status_local == "PENDENTE_VERIFICACAO":
                            st.warning("⏳ Enviado à Shopee, aguardando confirmação real", icon="🟡")
                            if st.button("Verificar status real", key=f"check_{dados_var['model_id']}", use_container_width=True):
                                discount_id = analise_var.get("discount_id_shopee")
                                status_api, detalhe = verificar_status_promocao(discount_id)

                                if status_api in ("ongoing", "upcoming"):
                                    analise_var["status_api_execucao"] = "SUCESSO"
                                elif status_api == "rejeitado":
                                    analise_var["status_api_execucao"] = "FALHOU"
                                # se vier "desconhecido", mantém PENDENTE_VERIFICACAO pra tentar de novo depois

                                salvar_cache_auditoria()

                                st.toast(f"Status: {status_api} — {detalhe}", icon="🔎")
                                st.rerun()

                        elif status_local == "FALHOU":
                            st.error("❌ A Shopee rejeitou esta promoção", icon="🔴")
                            if st.button("Tentar novamente", key=f"retry_{dados_var['model_id']}", use_container_width=True):
                                analise_var["status_api_execucao"] = None
                                st.rerun()

                        else:
                            # 3. FLUXO NORMAL DE VALIDAÇÃO E EXECUÇÃO
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
                                    with st.spinner("Sincronizando com a Shopee em tempo real..."):
                                        
                                        # 4. DISPARO DA API
                                        sucesso, msg = processar_acao_api(acao_var, dados_var, analise_var, novo_preco)
                                        
                                        if sucesso:
                                            # 5. MUTAÇÃO DO ESTADO NA MEMÓRIA RAM
                                            if acao_var in ("CRIAR_PROMOCAO", "CRIAR_COMBO"):
                                                # Assíncrono na Shopee — fica pendente até verificarmos de fato
                                                analise_var["status_api_execucao"] = "PENDENTE_VERIFICACAO"
                                                analise_var["discount_id_shopee"] = msg
                                            else:
                                                # Alteração de preço é síncrona — a Shopee confirma na hora
                                                analise_var["status_api_execucao"] = "SUCESSO"

                                            # 6. PERSISTÊNCIA FÍSICA NO DISCO (A prova de Refresh/F5)
                                            salvar_cache_auditoria()

                                            st.toast(f"Sincronização confirmada: {msg}", icon="✅")
                                            st.rerun() 
                                        else:
                                            st.error(f"Falha na validação com a Shopee: {msg}")

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
            "Previsão Vendas (30d)": a.get("previsao_vendas_30d", dados.get("previsao_vendas_30d", 0)),
            "Previsão Lucro (30d)": a.get("previsao_lucro_30d", dados.get("previsao_lucro_30d", 0)),
            "Evidência": classificar_confianca_evidencia(dados)[0],
            "Vendas observadas (30d)": dados.get("vendas_30d_macro", 0),
            "Cluster": a.get("cluster_mercado", dados.get("cluster_mercado", "Estável")),
        })

    if tabela_exec:
        df_pred = pd.DataFrame(tabela_exec).sort_values(["Previsão Lucro (30d)", "Previsão Lucro (7d)"], ascending=False)
        st.dataframe(
            df_pred,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Previsão Vendas (7d)": st.column_config.NumberColumn(format="%d un."),
                "Previsão Lucro (7d)": st.column_config.NumberColumn(format="R$ %.2f"),
                "Previsão Vendas (30d)": st.column_config.NumberColumn(format="%d un."),
                "Previsão Lucro (30d)": st.column_config.NumberColumn(format="R$ %.2f")
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
    st.caption("Acesse a defesa argumentativa do Conselho C-Level (CFO, CMO, COO) gerada pela IA para cada produto.")

    for iid, p in produtos_agrupados.items():
        var_base = p["variacoes"][0]
        with st.expander(f"Ler Parecer: {p['nome_produto']}"):
            st.markdown(f"**Recomendação Executiva:** {var_base.get('recomendacao_executiva', 'N/A')}")

            c1, c2, c3 = st.columns(3)
            with c1: st.info(f"**💰 Parecer CFO (Finanças):**\n\n{var_base.get('relatorio_cfo_financas', 'N/A')}")
            with c2: st.success(f"**🎯 Parecer CMO (Marketing):**\n\n{var_base.get('relatorio_cmo_marketing', 'N/A')}")
            with c3: st.warning(f"**🏭 Parecer COO (Operações):**\n\n{var_base.get('relatorio_coo_operacoes', 'N/A')}")
