"""
cerebro/dossie.py
=================
Extração do Data Warehouse e montagem do dossiê analítico por variação.

Melhorias sobre a versão monolítica anterior:
  1. Usa a view da migração 12 (vw_vendas_diarias_variacao) para vendas; o
     funil orgânico+ads é agregado inline com o filtro de janela dentro de
     cada lado do FULL JOIN (a view vw_funil_diario_item não permite o
     pushdown do predicado de data e forçaria varrer o histórico inteiro).
  2. Escrow rateado por valor do item dentro do pedido — antes, um pedido com
     2 variações somava o lucro do pedido inteiro em CADA variação (dupla
     contagem de lucro em pedidos multi-item).
  3. Tráfego/ads (dados no nível do anúncio) rateados por peso híbrido entre
     as variações: metade igualitário + metade proporcional às vendas de 30d.
     Antes o rateio era 100% igualitário, o que atribuía o mesmo tráfego a
     uma variação campeã e a uma variação morta.
  4. ACOS calculado dos totais (investimento/GMV) em vez de média das médias.

Todos os nomes de campo do dossiê são preservados — o fingerprint do cache
semântico, a UI e o motor de IA dependem deles.
"""

import psycopg2.extras
from loguru import logger

from utils.db_pool import get_connection
from cerebro import heuristicas
from cerebro.config import MigracaoPendenteError, memoizar_ttl
from cerebro.memoria import enriquecer_dossie_com_memoria

STATUS_CANCELADOS = "('CANCELLED', 'CANCELED', 'CANCELLED_BY_BUYER', 'IN_CANCEL')"


# ══════════════════════════════════════════════════════════════════════════════
# PRÉ-REQUISITOS DE SCHEMA
# ══════════════════════════════════════════════════════════════════════════════

@memoizar_ttl(300)
def _views_migration12_disponiveis() -> bool:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT to_regclass('public.vw_vendas_diarias_variacao') IS NOT NULL
                       AND to_regclass('public.vw_funil_diario_item') IS NOT NULL
                """)
                return bool(cur.fetchone()[0])
    except Exception as exc:
        logger.warning(f"Não foi possível verificar as views da migração 12: {exc}")
        return False


def garantir_tabela_historico_variacoes():
    """Rede de segurança para instalações sem a migração 12 aplicada."""
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


# ══════════════════════════════════════════════════════════════════════════════
# QUERY PRINCIPAL (janelas 7d/30d sobre as views de pré-agregação)
# ══════════════════════════════════════════════════════════════════════════════

QUERY_DOSSIE = f"""
WITH vendas_janelas AS (
    -- Vendas, pedidos e cancelamentos por variação, já sem pedidos cancelados
    SELECT
        model_id,
        COALESCE(SUM(unidades_vendidas) FILTER (WHERE data >= CURRENT_DATE - 7), 0)  AS qtd_7d,
        COUNT(*) FILTER (WHERE data >= CURRENT_DATE - 7 AND unidades_vendidas > 0)   AS dias_com_venda_7d,
        COALESCE(SUM(unidades_vendidas), 0)                                          AS qtd_30d,
        COUNT(*) FILTER (WHERE unidades_vendidas > 0)                                AS dias_com_venda_30d,
        COALESCE(SUM(unidades_vendidas) FILTER (
            WHERE data >= CURRENT_DATE - 14 AND data < CURRENT_DATE - 7), 0)         AS qtd_semana_anterior,
        COALESCE(SUM(pedidos) FILTER (WHERE data >= CURRENT_DATE - 7), 0)            AS pedidos_7d,
        COALESCE(SUM(pedidos_cancelados) FILTER (WHERE data >= CURRENT_DATE - 7), 0) AS cancelamentos_7d,
        COALESCE(SUM(pedidos), 0)                                                    AS pedidos_30d,
        COALESCE(SUM(pedidos_cancelados), 0)                                         AS cancelamentos_30d
    FROM vw_vendas_diarias_variacao
    WHERE data >= CURRENT_DATE - 30
    GROUP BY model_id
),
lucro_rateado AS (
    -- Escrow é do PEDIDO: rateia por participação de valor de cada item para
    -- não somar o lucro do pedido inteiro em cada variação (dupla contagem).
    SELECT
        i.model_id,
        p.data_hora_criacao::date AS data,
        SUM(
            COALESCE(
                r.lucro_liquido_absoluto
                    * (i.preco_praticado * i.quantidade) / NULLIF(tot.valor_pedido, 0),
                ((v.preco_venda_atual * 0.80) - 3.00) * i.quantidade
            )
        ) AS lucro_liquido,
        AVG(
            COALESCE(
                (r.comissao_shopee + r.taxa_servico + r.taxa_transacao)
                    * (i.preco_praticado * i.quantidade) / NULLIF(tot.valor_pedido, 0)
                    / NULLIF(i.quantidade, 0),
                (v.preco_venda_atual * 0.20) + 3.00
            )
        ) AS taxa_media_unitaria
    FROM fato_itens_pedido i
    JOIN fato_pedidos_venda p ON p.order_sn = i.order_sn
    JOIN dim_variacoes v ON v.model_id = i.model_id
    LEFT JOIN fato_repasse_escrow r ON r.order_sn = i.order_sn
    JOIN (
        -- Total do pedido calculado apenas para a janela de 30 dias: sem o
        -- filtro, este agregado varria TODO o histórico de itens a cada
        -- auditoria e crescia sem limite junto com a base.
        SELECT i2.order_sn, SUM(i2.preco_praticado * i2.quantidade) AS valor_pedido
        FROM fato_itens_pedido i2
        JOIN fato_pedidos_venda p2 ON p2.order_sn = i2.order_sn
        WHERE p2.data_hora_criacao >= CURRENT_DATE - INTERVAL '30 days'
        GROUP BY i2.order_sn
    ) tot ON tot.order_sn = i.order_sn
    WHERE p.data_hora_criacao >= CURRENT_DATE - INTERVAL '30 days'
      AND p.status_pedido NOT IN {STATUS_CANCELADOS}
    GROUP BY i.model_id, p.data_hora_criacao::date
),
lucro_janelas AS (
    SELECT
        model_id,
        COALESCE(SUM(lucro_liquido) FILTER (WHERE data >= CURRENT_DATE - 7), 0) AS receita_liquida_7d,
        COALESCE(SUM(lucro_liquido), 0)                                         AS receita_liquida_30d,
        AVG(taxa_media_unitaria) FILTER (WHERE data >= CURRENT_DATE - 7)        AS taxa_shopee_7d
    FROM lucro_rateado
    GROUP BY model_id
),
funil_janelas AS (
    -- Funil orgânico + pago unificado por item. COUNT(coluna) distingue
    -- "dado não coletado" (NULL) de "zero medido" — o escudo anti-alucinação.
    SELECT
        item_id,
        -- Janela de 7 dias
        SUM(impressoes_org)   FILTER (WHERE data >= CURRENT_DATE - 7) AS impressoes_org,
        COUNT(impressoes_org) FILTER (WHERE data >= CURRENT_DATE - 7) AS registros_impressoes_org,
        SUM(cliques_org)      FILTER (WHERE data >= CURRENT_DATE - 7) AS cliques_org,
        COUNT(cliques_org)    FILTER (WHERE data >= CURRENT_DATE - 7) AS registros_cliques_org,
        COALESCE(SUM(visitantes_unicos) FILTER (WHERE data >= CURRENT_DATE - 7), 0) AS visitas,
        COALESCE(SUM(adicoes_carrinho)  FILTER (WHERE data >= CURRENT_DATE - 7), 0) AS carrinhos,
        AVG(taxa_rejeicao) FILTER (WHERE data >= CURRENT_DATE - 7) AS rejeicao_media,
        COUNT(*) FILTER (WHERE data >= CURRENT_DATE - 7 AND granularidade_trafego = 'DIARIA') AS dias_trafego_7d,
        SUM(impressoes_ads)   FILTER (WHERE data >= CURRENT_DATE - 7) AS impressoes_ads,
        COUNT(impressoes_ads) FILTER (WHERE data >= CURRENT_DATE - 7) AS registros_impressoes_ads,
        SUM(cliques_ads)      FILTER (WHERE data >= CURRENT_DATE - 7) AS cliques_ads,
        COUNT(cliques_ads)    FILTER (WHERE data >= CURRENT_DATE - 7) AS registros_cliques_ads,
        COALESCE(SUM(investimento_ads) FILTER (WHERE data >= CURRENT_DATE - 7), 0) AS gasto_ads,
        COALESCE(SUM(gmv_ads)          FILTER (WHERE data >= CURRENT_DATE - 7), 0) AS gmv_ads,
        COUNT(*) FILTER (WHERE data >= CURRENT_DATE - 7 AND granularidade_ads = 'DIARIA') AS dias_ads_7d,
        -- Janela de 30 dias (todas as linhas do WHERE)
        SUM(impressoes_org)   AS impressoes_org_30d,
        COUNT(impressoes_org) AS registros_impressoes_org_30d,
        SUM(cliques_org)      AS cliques_org_30d,
        COUNT(cliques_org)    AS registros_cliques_org_30d,
        COALESCE(SUM(visitantes_unicos), 0) AS visitas_30d,
        COALESCE(SUM(adicoes_carrinho), 0)  AS carrinhos_30d,
        COUNT(*) FILTER (WHERE granularidade_trafego = 'DIARIA') AS dias_trafego_30d,
        SUM(impressoes_ads)   AS impressoes_ads_30d,
        COUNT(impressoes_ads) AS registros_impressoes_ads_30d,
        SUM(cliques_ads)      AS cliques_ads_30d,
        COUNT(cliques_ads)    AS registros_cliques_ads_30d,
        COALESCE(SUM(investimento_ads), 0) AS gasto_ads_30d,
        COALESCE(SUM(gmv_ads), 0)          AS gmv_ads_30d,
        COALESCE(SUM(conversoes_ads), 0)   AS conversoes_ads_30d,
        COALESCE(SUM(itens_vendidos_ads), 0) AS itens_vendidos_ads_30d,
        COUNT(*) FILTER (WHERE granularidade_ads = 'DIARIA') AS dias_ads_30d
    FROM (
        -- Mesma forma da vw_funil_diario_item, mas com o filtro de janela DENTRO
        -- de cada lado do FULL JOIN. Na view, o WHERE sobre COALESCE(t.data,
        -- a.data_registro) não é empurrado para os lados do FULL JOIN pelo
        -- planner: toda auditoria materializava o histórico COMPLETO de tráfego
        -- e ads antes de filtrar. Com o filtro interno, cada lado usa seu índice
        -- de data e o custo fica proporcional à janela, não ao histórico.
        SELECT
            COALESCE(t.item_id, a.item_id)      AS item_id,
            COALESCE(t.data, a.data_registro)   AS data,
            t.impressoes                        AS impressoes_org,
            t.cliques                           AS cliques_org,
            t.visitantes_unicos,
            t.adicoes_carrinho,
            t.taxa_rejeicao,
            t.granularidade_origem              AS granularidade_trafego,
            a.impressoes_ads,
            a.cliques_ads,
            a.investimento_ads,
            a.gmv_ads,
            a.conversoes_ads,
            a.itens_vendidos_ads,
            a.granularidade_ads
        FROM (
            SELECT * FROM fato_trafego_diario WHERE data >= CURRENT_DATE - 30
        ) t
        FULL OUTER JOIN (
            SELECT
                item_id,
                data_registro,
                SUM(impressoes)      AS impressoes_ads,
                SUM(cliques)         AS cliques_ads,
                SUM(investimento)    AS investimento_ads,
                SUM(vendas_gmv)      AS gmv_ads,
                SUM(conversoes)      AS conversoes_ads,
                SUM(itens_vendidos)  AS itens_vendidos_ads,
                MIN(granularidade_origem) AS granularidade_ads
            FROM fato_ads_performance_produto
            WHERE data_registro >= CURRENT_DATE - 30
            GROUP BY item_id, data_registro
        ) a ON a.item_id = t.item_id AND a.data_registro = t.data
    ) funil_30d
    GROUP BY item_id
),
variacoes_por_item AS (
    SELECT v.item_id, COUNT(*) AS qtd_variacoes
    FROM dim_variacoes v
    WHERE v.nome_variacao NOT ILIKE '%Excluída%'
      AND v.nome_variacao NOT ILIKE '%Excluida%'
    GROUP BY v.item_id
),
metricas_importadas_7d AS (
    -- Nomes reais do parentskudetail: vendas em BRL existem em DOIS estágios
    -- (pedido realizado e pedido pago) — somar ambos dobraria; usamos o PAGO.
    -- O padrão antigo '%pedido%' somava dinheiro + contagens + taxas de
    -- conversão num número só; unidades (pago) é a medida honesta de vendas.
    SELECT
        item_id,
        SUM(CASE WHEN metric_name ILIKE 'unidade%'
                  AND metric_name NOT ILIKE '%carrinho%'
                  AND metric_name NOT ILIKE '%realizado%'
             THEN metric_value ELSE 0 END) AS vendas_importadas_7d,
        SUM(CASE WHEN metric_name ILIKE 'receita%' OR metric_name ILIKE 'gmv%'
                  OR (metric_name ILIKE 'venda%brl'
                      AND metric_name NOT ILIKE '%por_pedido%'
                      AND metric_name NOT ILIKE '%realizado%')
             THEN metric_value ELSE 0 END) AS receita_importada_7d,
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
    -- Padrões alinhados aos nomes REAIS do export shop-stats, que grava CINCO
    -- métricas começando com 'vendas': vendas_brl, vendas_sem_os_descontos_da_
    -- shopee, vendas_por_pedido (ticket médio), vendas_canceladas e vendas_
    -- devolvidas_reembolsadas. Só vendas_brl é receita — somar todas mais que
    -- dobraria o número.
    SELECT
        SUM(CASE WHEN metric_name ILIKE 'receita%' OR metric_name ILIKE 'gmv%'
                  OR (metric_name ILIKE 'venda%'
                      AND metric_name NOT ILIKE '%cancelad%'
                      AND metric_name NOT ILIKE '%devolvid%'
                      AND metric_name NOT ILIKE '%descont%'
                      AND metric_name NOT ILIKE '%por_pedido%')
             THEN metric_value ELSE 0 END) AS receita_macro_7d,
        AVG(CASE WHEN metric_name ILIKE '%convers%' AND metric_name NOT ILIKE '%carrinho%' THEN metric_value ELSE NULL END) AS conversao_macro_7d,
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
    -- Último registro CONHECIDO até cada marco (hoje, -7d, -30d), e não a data
    -- exata: o casamento exato zerava preço/estoque históricos (e, com eles,
    -- elasticidade e tendência de preço) sempre que a sincronização pulava um
    -- dia. A janela de 35 dias também limita a leitura ao necessário — antes,
    -- a CTE varria o histórico inteiro a cada auditoria.
    SELECT
        model_id,
        (ARRAY_AGG(preco_venda_atual ORDER BY data_registro DESC))[1] AS preco_hoje,
        (ARRAY_AGG(preco_venda_atual ORDER BY data_registro DESC)
            FILTER (WHERE data_registro <= CURRENT_DATE - 7))[1]      AS preco_7d_atras,
        (ARRAY_AGG(preco_venda_atual ORDER BY data_registro DESC)
            FILTER (WHERE data_registro <= CURRENT_DATE - 30))[1]     AS preco_30d_atras,
        (ARRAY_AGG(estoque_shopee ORDER BY data_registro DESC))[1]    AS estoque_hoje,
        (ARRAY_AGG(estoque_shopee ORDER BY data_registro DESC)
            FILTER (WHERE data_registro <= CURRENT_DATE - 7))[1]      AS estoque_7d_atras,
        (ARRAY_AGG(estoque_shopee ORDER BY data_registro DESC)
            FILTER (WHERE data_registro <= CURRENT_DATE - 30))[1]     AS estoque_30d_atras
    FROM fato_historico_variacoes
    WHERE data_registro BETWEEN CURRENT_DATE - 35 AND CURRENT_DATE
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

    COALESCE(vj.qtd_7d, 0)               AS vendas_7d,
    COALESCE(vj.dias_com_venda_7d, 0)    AS dias_com_venda_7d,
    COALESCE(vj.qtd_30d, 0)              AS vendas_30d,
    COALESCE(vj.dias_com_venda_30d, 0)   AS dias_com_venda_30d,
    COALESCE(vj.qtd_semana_anterior, 0)  AS vendas_semana_passada,
    COALESCE(vj.pedidos_7d, 0)           AS pedidos_7d,
    COALESCE(vj.cancelamentos_7d, 0)     AS cancelamentos_7d,
    COALESCE(vj.pedidos_30d, 0)          AS pedidos_30d,
    COALESCE(vj.cancelamentos_30d, 0)    AS cancelamentos_30d,
    SUM(COALESCE(vj.qtd_30d, 0)) OVER (PARTITION BY p.item_id) AS vendas_30d_item_total,

    COALESCE(lj.receita_liquida_7d, 0)   AS receita_liquida_7d,
    COALESCE(lj.receita_liquida_30d, 0)  AS receita_liquida_30d,
    COALESCE(lj.taxa_shopee_7d, 0)       AS taxa_shopee_unitaria,

    -- Funil Orgânico e Pago (nível do item; rateado por variação no Python)
    COALESCE(f.impressoes_org, 0)        AS impressoes_org,
    COALESCE(f.registros_impressoes_org, 0) AS registros_impressoes_org,
    COALESCE(f.cliques_org, 0)           AS cliques_org,
    COALESCE(f.registros_cliques_org, 0) AS registros_cliques_org,
    COALESCE(f.rejeicao_media, 0)        AS rejeicao_media,
    COALESCE(f.impressoes_ads, 0)        AS impressoes_ads,
    COALESCE(f.registros_impressoes_ads, 0) AS registros_impressoes_ads,
    COALESCE(f.cliques_ads, 0)           AS cliques_ads,
    COALESCE(f.registros_cliques_ads, 0) AS registros_cliques_ads,
    COALESCE(f.gmv_ads, 0)               AS gmv_ads,
    COALESCE(f.visitas, 0)               AS visitas_7d,
    COALESCE(f.carrinhos, 0)             AS carrinhos_7d,
    COALESCE(f.dias_trafego_7d, 0)       AS dias_trafego_7d,
    COALESCE(f.gasto_ads, 0)             AS gasto_ads_7d,
    COALESCE(f.dias_ads_7d, 0)           AS dias_ads_7d,

    COALESCE(f.visitas_30d, 0)           AS visitas_30d,
    COALESCE(f.carrinhos_30d, 0)         AS carrinhos_30d,
    COALESCE(f.dias_trafego_30d, 0)      AS dias_trafego_30d,
    COALESCE(f.impressoes_org_30d, 0)    AS impressoes_org_30d,
    COALESCE(f.registros_impressoes_org_30d, 0) AS registros_impressoes_org_30d,
    COALESCE(f.cliques_org_30d, 0)       AS cliques_org_30d,
    COALESCE(f.registros_cliques_org_30d, 0) AS registros_cliques_org_30d,
    COALESCE(f.gasto_ads_30d, 0)         AS gasto_ads_30d,
    COALESCE(f.dias_ads_30d, 0)          AS dias_ads_30d,
    COALESCE(f.impressoes_ads_30d, 0)    AS impressoes_ads_30d,
    COALESCE(f.registros_impressoes_ads_30d, 0) AS registros_impressoes_ads_30d,
    COALESCE(f.cliques_ads_30d, 0)       AS cliques_ads_30d,
    COALESCE(f.registros_cliques_ads_30d, 0) AS registros_cliques_ads_30d,
    COALESCE(f.gmv_ads_30d, 0)           AS gmv_ads_30d,
    COALESCE(f.conversoes_ads_30d, 0)    AS conversoes_ads_30d,
    COALESCE(f.itens_vendidos_ads_30d, 0) AS itens_vendidos_ads_30d,

    COALESCE(vi.qtd_variacoes, 1)        AS qtd_variacoes_produto,

    COALESCE(mi.vendas_importadas_7d, 0) AS vendas_importadas_7d,
    COALESCE(mi.receita_importada_7d, 0) AS receita_importada_7d,
    COALESCE(mi.cancelamentos_importados_7d, 0) AS cancelamentos_importados_7d,
    COALESCE(mi.devolucoes_importadas_7d, 0) AS devolucoes_importadas_7d,
    COALESCE(mi.reembolsos_importados_7d, 0) AS reembolsos_importados_7d,
    COALESCE(mi.estoque_importado_7d, 0) AS estoque_importado_7d,
    COALESCE(mi.custo_importado_7d, 0)   AS custo_importado_7d,
    COALESCE(macro.receita_macro_7d, 0)  AS receita_macro_7d,
    COALESCE(macro.conversao_macro_7d, 0) AS conversao_macro_7d,
    COALESCE(macro.roas_macro_7d, 0)     AS roas_macro_7d,
    COALESCE(macro.visitas_macro_7d, 0)  AS visitas_macro_7d,
    COALESCE(macro.estoque_macro_7d, 0)  AS estoque_macro_7d,

    -- COALESCE em máquina/tempo: o mapeamento enxuto (só filamento + peso, da
    -- página de Lucro) não cadastra máquina — sem o COALESCE, o NULL da
    -- energia anulava o custo do material inteiro.
    (
        (
            (CASE WHEN mat.unidade_medida = 'kg'
                  THEN (eng.peso_gramas / 1000.0)
                  ELSE eng.peso_gramas END
             * mat.custo_por_unidade)
            + (COALESCE(eng.tempo_impressao_minutos, 0) * COALESCE(maq.custo_energia_hora, 0) / 60.0)
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
LEFT JOIN vendas_janelas vj       ON v.model_id  = vj.model_id
LEFT JOIN lucro_janelas  lj       ON v.model_id  = lj.model_id
LEFT JOIN funil_janelas  f        ON p.item_id   = f.item_id
LEFT JOIN variacoes_por_item vi   ON p.item_id   = vi.item_id
LEFT JOIN metricas_importadas_7d mi ON p.item_id = mi.item_id
LEFT JOIN macro_loja_7d macro     ON TRUE
LEFT JOIN memoria_ia    m         ON v.model_id  = m.model_id
LEFT JOIN historico_variacoes h   ON v.model_id  = h.model_id
WHERE p.status_shopee = 'NORMAL'
  AND v.nome_variacao NOT ILIKE '%Excluída%'
  AND v.nome_variacao NOT ILIKE '%Excluida%';
"""


def _peso_rateio_variacao(vendas_30d_var: int, vendas_30d_item: int, qtd_variacoes: int) -> float:
    """Peso híbrido de rateio: metade igualitário, metade por participação nas
    vendas de 30 dias. A soma dos pesos entre as variações de um item é 1, o
    que conserva os totais do anúncio; variações sem venda ainda recebem parte
    do tráfego (não são zeradas artificialmente)."""
    igualitario = 1.0 / max(1, qtd_variacoes)
    if vendas_30d_item <= 0:
        return igualitario
    participacao = vendas_30d_var / vendas_30d_item
    return 0.5 * igualitario + 0.5 * participacao


def _ratear_int(valor, peso: float):
    return int(round(int(valor or 0) * peso))


def _ratear_float(valor, peso: float) -> float:
    return float(valor or 0) * peso


# ══════════════════════════════════════════════════════════════════════════════
# MONTAGEM DO DOSSIÊ
# ══════════════════════════════════════════════════════════════════════════════

def gerar_dossie_produtos_com_memoria() -> list[dict]:
    """Extrai o DW, aplica a camada determinística e anexa a memória analítica."""
    if not _views_migration12_disponiveis():
        raise MigracaoPendenteError(
            "As views de pré-agregação não existem no banco. "
            "Execute `python init_db/aplicar_migrations.py` (aplica as migrações pendentes, "
            "incluindo a 12) e recarregue a página."
        )

    garantir_tabela_historico_variacoes()

    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(QUERY_DOSSIE)
            registros = cur.fetchall()

    dossie = [_montar_dados_variacao(r) for r in registros]
    return enriquecer_dossie_com_memoria(dossie)


def _montar_dados_variacao(r) -> dict:
    """Converte uma linha do DW no dicionário analítico de uma variação."""
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

    vendas       = int(r["vendas_7d"])
    vendas_30d   = int(r["vendas_30d"] or 0)
    vendas_antes = int(r["vendas_semana_passada"])
    qtd_variacoes = max(1, int(r["qtd_variacoes_produto"] or 1))
    vendas_30d_item = int(r["vendas_30d_item_total"] or 0)

    # Rateio híbrido: métricas do anúncio distribuídas entre as variações
    # metade por igual, metade proporcional às vendas de 30 dias.
    peso = _peso_rateio_variacao(vendas_30d, vendas_30d_item, qtd_variacoes)

    gasto_ads     = _ratear_float(r["gasto_ads_7d"], peso)
    visitas       = _ratear_int(r["visitas_7d"], peso)
    carrinhos     = _ratear_int(r["carrinhos_7d"], peso)
    gasto_ads_30d = _ratear_float(r["gasto_ads_30d"], peso)
    visitas_30d   = _ratear_int(r["visitas_30d"], peso)
    carrinhos_30d = _ratear_int(r["carrinhos_30d"], peso)

    impressoes_org = _ratear_int(r["impressoes_org"], peso)
    cliques_org    = _ratear_int(r["cliques_org"], peso)
    rejeicao_media = float(r["rejeicao_media"] or 0)
    org_impressoes_disponiveis = int(r["registros_impressoes_org"] or 0) > 0 and (impressoes_org > 0 or visitas == 0)
    org_cliques_disponiveis = int(r["registros_cliques_org"] or 0) > 0 and (cliques_org > 0 or visitas == 0)

    impressoes_ads = _ratear_int(r["impressoes_ads"], peso)
    cliques_ads    = _ratear_int(r["cliques_ads"], peso)
    gmv_ads        = _ratear_float(r["gmv_ads"], peso)
    gasto_ads_item = float(r["gasto_ads_7d"] or 0)
    gmv_ads_item   = float(r["gmv_ads"] or 0)
    # ACOS dos totais do anúncio (média de médias distorcia campanhas de pesos diferentes)
    acos_medio = round(gasto_ads_item / gmv_ads_item * 100, 2) if gmv_ads_item > 0 else 0.0
    ads_impressoes_disponiveis = int(r["registros_impressoes_ads"] or 0) > 0 and (impressoes_ads > 0 or gasto_ads == 0)
    ads_cliques_disponiveis = int(r["registros_cliques_ads"] or 0) > 0 and (cliques_ads > 0 or gasto_ads == 0)

    ctr_org = round((cliques_org / impressoes_org) * 100, 2) if org_impressoes_disponiveis and org_cliques_disponiveis and impressoes_org > 0 else None
    ctr_ads = round((cliques_ads / impressoes_ads) * 100, 2) if ads_impressoes_disponiveis and ads_cliques_disponiveis and impressoes_ads > 0 else None

    impressoes_org_30d = _ratear_int(r["impressoes_org_30d"], peso)
    cliques_org_30d    = _ratear_int(r["cliques_org_30d"], peso)
    org_impressoes_30d_disponiveis = int(r["registros_impressoes_org_30d"] or 0) > 0 and (impressoes_org_30d > 0 or visitas_30d == 0)
    org_cliques_30d_disponiveis = int(r["registros_cliques_org_30d"] or 0) > 0 and (cliques_org_30d > 0 or visitas_30d == 0)
    ctr_org_30d = round((cliques_org_30d / impressoes_org_30d) * 100, 2) if org_impressoes_30d_disponiveis and org_cliques_30d_disponiveis and impressoes_org_30d > 0 else None

    impressoes_ads_30d = _ratear_int(r["impressoes_ads_30d"], peso)
    cliques_ads_30d    = _ratear_int(r["cliques_ads_30d"], peso)
    ads_impressoes_30d_disponiveis = int(r["registros_impressoes_ads_30d"] or 0) > 0 and (impressoes_ads_30d > 0 or gasto_ads_30d == 0)
    ads_cliques_30d_disponiveis = int(r["registros_cliques_ads_30d"] or 0) > 0 and (cliques_ads_30d > 0 or gasto_ads_30d == 0)
    ctr_ads_30d = round((cliques_ads_30d / impressoes_ads_30d) * 100, 2) if ads_impressoes_30d_disponiveis and ads_cliques_30d_disponiveis and impressoes_ads_30d > 0 else None
    gmv_ads_30d = _ratear_float(r["gmv_ads_30d"], peso)

    # O ESCUDO ANTI-ALUCINAÇÃO: se um item teve visitas/gasto mas impressões
    # vieram 0, a planilha não tinha a coluna — enviamos None em vez de 0 para
    # a IA não concluir shadowban.
    dados_org_completos = True if impressoes_org > 0 or visitas == 0 else False

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

    contexto_previsao_7d = {
        "vendas_7d_reais": vendas,
        "vendas_30d_macro": vendas_30d,
        "tendencia_vendas_WoW_perc": tendencia_perc,
        "TRAFEGO_taxa_conversao_perc": taxa_conversao,
        "ADS_roas_atual": roas_atual,
        "LOGISTICA_dias_estoque_restante": dias_estoque,
        "LOGISTICA_capacidade_material_restante": capacidade_maxima,
        "estoque_shopee_hoje": estoque_hoje,
    }
    contexto_previsao_30d = {
        "vendas_7d_reais": vendas,
        "vendas_30d_reais": vendas_30d,
        "TRAFEGO_taxa_conversao_perc": taxa_conversao,
        "TRAFEGO_taxa_conversao_30d_perc": taxa_conversao_30d,
        "LOGISTICA_capacidade_material_restante": capacidade_maxima,
    }
    previsao_vendas_7d = heuristicas.calcular_previsao_demanda_7d(contexto_previsao_7d)
    previsao_vendas_30d = heuristicas.calcular_previsao_demanda_30d(contexto_previsao_30d)

    return {
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

        # Transparência do rateio híbrido (novo na v2)
        "RATEIO_peso_variacao": round(peso, 4),

        # --- FUNIL DE DADOS (com escudo anti-alucinação de nulos) ---
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
        "ADS_conversoes_30d": _ratear_int(r["conversoes_ads_30d"], peso),
        "ADS_itens_vendidos_30d": _ratear_int(r["itens_vendidos_ads_30d"], peso),
        # -------------------------------------------------------------

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
        "elasticidade_preco_volume": heuristicas.calcular_elasticidade_preco_volume(
            preco_hoje, preco_7d, vendas, vendas_antes
        ),

        # Chaves Macro para a IA e o Gatekeeper
        "vendas_30d_macro": vendas_30d,
        "visitas_30d_macro": int(r["visitas_30d"] or 0),
        "carrinhos_30d_macro": int(r["carrinhos_30d"] or 0),
        "gasto_ads_30d_macro": float(r["gasto_ads_30d"] or 0),

        "previsao_vendas_7d": previsao_vendas_7d,
        "previsao_lucro_7d": round(
            (previsao_vendas_7d * margem_unitaria_real) - (gasto_ads * 0.9), 2
        ),
        "previsao_vendas_30d": previsao_vendas_30d,
        "previsao_lucro_30d": round(
            previsao_vendas_30d * margem_unitaria_real - (gasto_ads_30d * 0.9), 2
        ),
        "cluster_mercado": heuristicas.classificar_cluster({
            "lucro_liquido_real_7d": lucro_operacional,
            "ADS_roas_atual": roas_atual,
            "LOGISTICA_dias_estoque_restante": dias_estoque,
            "TRAFEGO_taxa_conversao_perc": taxa_conversao,
            "vendas_7d_reais": vendas,
        }),
        "recomendacao_executiva": heuristicas.gerar_recomendacao_executiva({
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
