-- =============================================================================
-- MIGRATION 19: CUSTO POR PEÇA E FINANCEIRO POR ITEM DE PEDIDO (FONTE ÚNICA)
-- Descrição:
--   O custo de fabricação era recalculado em três lugares (dossiê, vw_saude_
--   produto e à mão pelo chat). O chat juntou a engenharia com as vendas
--   diárias ANTES de agregar e somou o custo 7 vezes (R$ 92,34 no lugar de
--   R$ 12,83). Estas views dão uma resposta única e já agregada:
--
--   1. vw_custo_fabricacao_variacao: UMA linha por variação mapeada, com cada
--      parcela do custo separada (material, máquina, embalagem, perda).
--
--   2. vw_financeiro_item_pedido: UMA linha por item de pedido não cancelado,
--      com o repasse da Shopee rateado pelo valor do item e detalhado
--      (migração 18), o custo de fabricação e o lucro antes de anúncios.
--      Pedido ainda não liquidado recebe repasse ESTIMADO pela fração real que
--      a própria variação costuma receber (≥ 3 pedidos liquidados sem
--      devolução nos últimos 120 dias); sem histórico, pela fração da loja; sem
--      nada, 80% do valor − R$ 3 por unidade. origem_repasse diz qual valeu.
--      A estimativa antiga (80% − R$ 3) chegava a R$ 22,52 num produto que
--      recebe R$ 17,84 de verdade.
--
--   Recarga de anúncios (recarga_ads): desde 06/2026 a Shopee desconta 10,0%
--   do preço em ~95% dos pedidos para recarregar o SALDO de anúncios (~R$ 110
--   por mês, enquanto o gasto real importado é ~R$ 57 por mês). Ela não é o
--   custo do anúncio: é dinheiro indo para o saldo. Por isso:
--     retido_shopee   = valor_item − repasse − recarga_ads  (só taxas/descontos)
--     lucro_antes_ads = repasse + recarga_ads − custo_fabricacao
--   e o custo de anúncios entra UMA vez, depois, pelo gasto real importado.
-- SEGURO PARA RODAR MÚLTIPLAS VEZES.
-- =============================================================================

BEGIN;

-- DROP + CREATE (e não CREATE OR REPLACE): permite mudar colunas da view.
DROP VIEW IF EXISTS vw_financeiro_item_pedido;
DROP VIEW IF EXISTS vw_custo_fabricacao_variacao;

CREATE VIEW vw_custo_fabricacao_variacao AS
SELECT
    v.item_id,
    v.model_id,
    p.nome_atual                                   AS produto,
    v.nome_variacao                                AS variacao,
    mat.nome                                       AS material,
    mat.unidade_medida                             AS unidade_material,
    mat.custo_por_unidade                          AS preco_material,
    ROUND(calc.preco_grama, 6)                     AS preco_material_por_grama,
    eng.peso_gramas,
    maq.nome_modelo                                AS maquina,
    COALESCE(maq.custo_energia_hora, 0)            AS custo_maquina_hora,
    COALESCE(eng.tempo_impressao_minutos, 0)       AS tempo_impressao_minutos,
    COALESCE(eng.taxa_perda_percentual, 0)         AS perda_percentual,
    ROUND(calc.material, 4)                        AS custo_material,
    ROUND(calc.maquina, 4)                         AS custo_maquina,
    ROUND(calc.embalagem, 4)                       AS custo_embalagem,
    ROUND((calc.material + calc.maquina + calc.embalagem)
          * COALESCE(eng.taxa_perda_percentual, 0) / 100.0, 4) AS custo_perda,
    ROUND((calc.material + calc.maquina + calc.embalagem)
          * (1 + COALESCE(eng.taxa_perda_percentual, 0) / 100.0), 4) AS custo_total
FROM map_engenharia_produto eng
JOIN dim_variacoes v   ON v.model_id = eng.model_id
JOIN dim_produtos p    ON p.item_id = v.item_id
JOIN dim_materiais mat ON mat.id_material = eng.id_material   -- sem material = sem custo mapeado
LEFT JOIN dim_maquinas maq ON maq.id_maquina = eng.id_maquina
CROSS JOIN LATERAL (
    SELECT
        CASE WHEN mat.unidade_medida = 'kg' THEN mat.custo_por_unidade / 1000.0
             ELSE mat.custo_por_unidade END                                     AS preco_grama,
        eng.peso_gramas
            * CASE WHEN mat.unidade_medida = 'kg' THEN mat.custo_por_unidade / 1000.0
                   ELSE mat.custo_por_unidade END                               AS material,
        COALESCE(eng.tempo_impressao_minutos, 0) * COALESCE(maq.custo_energia_hora, 0) / 60.0 AS maquina,
        COALESCE(eng.custo_embalagem, 0)                                        AS embalagem
) calc;

COMMENT ON VIEW vw_custo_fabricacao_variacao IS
    'Custo de fabricação por PEÇA, uma linha por variação. Para custo de N vendas: custo_total × unidades já somadas (nunca some esta view depois de juntar com vendas).';


CREATE VIEW vw_financeiro_item_pedido AS
WITH itens AS (
    SELECT
        i.order_sn,
        p.data_hora_criacao,
        p.data_hora_criacao::date                                   AS data,
        p.status_pedido,
        COALESCE(v.item_id, i.model_id)                             AS item_id,
        i.model_id,
        i.quantidade,
        i.preco_praticado                                           AS preco_unitario,
        i.preco_praticado * i.quantidade                            AS valor_item,
        SUM(i.preco_praticado * i.quantidade) OVER (PARTITION BY i.order_sn) AS valor_pedido
    FROM fato_itens_pedido i
    JOIN fato_pedidos_venda p ON p.order_sn = i.order_sn
    LEFT JOIN dim_variacoes v ON v.model_id = i.model_id
    WHERE p.status_pedido NOT IN ('CANCELLED', 'CANCELED', 'CANCELLED_BY_BUYER', 'IN_CANCEL', 'UNPAID')
),
base AS (
    SELECT
        it.*,
        COALESCE(it.valor_item / NULLIF(it.valor_pedido, 0), 1.0) AS participacao,
        e.order_sn IS NOT NULL                                     AS repasse_liquidado,
        e.detalhado_em IS NOT NULL                                 AS repasse_detalhado,
        e.comissao_shopee, e.taxa_servico, e.taxa_transacao, e.comissao_afiliado,
        e.cupom_vendedor, e.recarga_ads, e.seguro_frete, e.frete_liquido_vendedor,
        e.reembolso_devolucao, e.custo_frete_reverso, e.outros_ajustes, e.ajuste_pos_venda,
        e.lucro_liquido_absoluto
    FROM itens it
    LEFT JOIN fato_repasse_escrow e ON e.order_sn = it.order_sn
),
fracao_variacao AS (
    -- Quanto do valor vendido vira repasse (e recarga de anúncios) nesta
    -- variação: pedidos liquidados, sem devolução, últimos 120 dias.
    SELECT model_id,
           SUM(lucro_liquido_absoluto * participacao) / NULLIF(SUM(valor_item), 0)        AS fracao,
           SUM(COALESCE(recarga_ads, 0) * participacao) / NULLIF(SUM(valor_item), 0)     AS fracao_recarga,
           COUNT(*) AS pedidos
    FROM base
    WHERE repasse_liquidado AND COALESCE(reembolso_devolucao, 0) = 0 AND COALESCE(ajuste_pos_venda, 0) >= 0
      AND data_hora_criacao >= CURRENT_DATE - 120
    GROUP BY model_id
),
fracao_loja AS (
    SELECT SUM(lucro_liquido_absoluto * participacao) / NULLIF(SUM(valor_item), 0)    AS fracao,
           SUM(COALESCE(recarga_ads, 0) * participacao) / NULLIF(SUM(valor_item), 0) AS fracao_recarga
    FROM base
    WHERE repasse_liquidado AND COALESCE(reembolso_devolucao, 0) = 0 AND COALESCE(ajuste_pos_venda, 0) >= 0
      AND data_hora_criacao >= CURRENT_DATE - 120
),
calculado AS (
    SELECT
        b.*,
        CASE
            WHEN b.repasse_liquidado THEN 'REAL'
            WHEN fv.pedidos >= 3     THEN 'ESTIMADO_PELO_PRODUTO'
            WHEN fl.fracao IS NOT NULL THEN 'ESTIMADO_PELA_LOJA'
            ELSE 'ESTIMADO_PADRAO'
        END AS origem_repasse,
        CASE
            WHEN b.repasse_liquidado THEN b.lucro_liquido_absoluto * b.participacao
            WHEN fv.pedidos >= 3     THEN b.valor_item * fv.fracao
            WHEN fl.fracao IS NOT NULL THEN b.valor_item * fl.fracao
            ELSE b.valor_item * 0.80 - 3.00 * b.quantidade
        END AS repasse_calc,
        CASE
            WHEN b.repasse_liquidado THEN COALESCE(b.recarga_ads, 0) * b.participacao
            WHEN fv.pedidos >= 3     THEN b.valor_item * COALESCE(fv.fracao_recarga, 0)
            WHEN fl.fracao IS NOT NULL THEN b.valor_item * COALESCE(fl.fracao_recarga, 0)
            ELSE 0
        END AS recarga_calc,
        c.custo_total
    FROM base b
    LEFT JOIN fracao_variacao fv ON fv.model_id = b.model_id
    CROSS JOIN fracao_loja fl
    LEFT JOIN vw_custo_fabricacao_variacao c ON c.model_id = b.model_id
)
SELECT
    order_sn,
    data,
    data_hora_criacao,
    status_pedido,
    item_id,
    model_id,
    quantidade,
    preco_unitario,
    valor_item,
    repasse_liquidado,
    repasse_detalhado,
    origem_repasse,
    -- Descontos da Shopee rateados pelo valor do item (NULL = pedido não liquidado)
    ROUND(comissao_shopee * participacao, 2)        AS comissao_shopee,
    ROUND(taxa_servico * participacao, 2)           AS taxa_servico,
    ROUND(taxa_transacao * participacao, 2)         AS taxa_transacao,
    ROUND(comissao_afiliado * participacao, 2)      AS comissao_afiliado,
    ROUND(cupom_vendedor * participacao, 2)         AS cupom_vendedor,
    ROUND(seguro_frete * participacao, 2)           AS seguro_frete,
    ROUND(frete_liquido_vendedor * participacao, 2) AS frete_liquido_vendedor,
    ROUND(reembolso_devolucao * participacao, 2)    AS reembolso_devolucao,
    ROUND(custo_frete_reverso * participacao, 2)    AS custo_frete_reverso,
    ROUND(outros_ajustes * participacao, 2)         AS outros_ajustes,
    -- Ajuste da Shopee depois de pagar (negativo = tirou dinheiro, ex.: devolução tardia)
    ROUND(ajuste_pos_venda * participacao, 2)       AS ajuste_pos_venda,
    -- Recarga do saldo de anúncios: real quando liquidado, estimada senão
    ROUND(recarga_calc, 2)                          AS recarga_ads,
    ROUND(repasse_calc, 2)                          AS repasse,
    -- Tudo que a Shopee ficou, exceto a recarga de anúncios (taxas + descontos + reembolsos)
    ROUND(valor_item - repasse_calc - recarga_calc, 2) AS retido_shopee,
    COALESCE(reembolso_devolucao, 0) > 0 OR COALESCE(ajuste_pos_venda, 0) < 0 AS houve_devolucao,
    custo_total IS NOT NULL                         AS custo_mapeado,
    ROUND(custo_total, 2)                           AS custo_fabricacao_unitario,
    ROUND(COALESCE(custo_total, 0) * quantidade, 2) AS custo_fabricacao,
    -- Recarga volta para o lucro: o custo de anúncios entra depois, uma vez só, pelo gasto real
    ROUND(repasse_calc + recarga_calc - COALESCE(custo_total, 0) * quantidade, 2) AS lucro_antes_ads
FROM calculado;

COMMENT ON VIEW vw_financeiro_item_pedido IS
    'Uma linha por item de pedido não cancelado: preço, descontos da Shopee rateados, recarga de anúncios, repasse (REAL ou ESTIMADO_*), custo de fabricação e lucro antes de anúncios (= repasse + recarga − custo). Some colunas livremente: não há duplicação. Anúncios: subtraia o gasto real (fato_ads_performance_produto) uma vez; não subtraia a recarga de novo.';

COMMIT;

-- =============================================================================
-- VALIDAÇÃO PÓS-MIGRAÇÃO
-- =============================================================================
SELECT
    'Migração 19 aplicada com sucesso!' AS status,
    (SELECT COUNT(*) FROM vw_custo_fabricacao_variacao) AS variacoes_com_custo,
    (SELECT COUNT(*) FROM vw_financeiro_item_pedido)    AS itens_de_pedido;
