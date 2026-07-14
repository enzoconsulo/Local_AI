-- =============================================================================
-- MIGRATION 12: CONFIABILIDADE DA SINCRONIZAÇÃO + PRÉ-AGREGAÇÕES PARA O CÉREBRO
-- Descrição:
--   1. Formaliza fato_historico_variacoes (antes criada ad-hoc pelo código).
--   2. Cria sys_lotes_importacao: idempotência real por hash de arquivo, que
--      impede dupla contagem quando a mesma planilha é enviada duas vezes e
--      permite detectar períodos sobrepostos com rateios divergentes.
--   3. Cria views de pré-agregação diária (funil por item e vendas por
--      variação) que o Cérebro IA usará no lugar de recalcular 15 CTEs.
--   4. Remove a semente órfã 'TRAFEGO_ADS' (o código usa TRAFEGO_ORG/ADS_AVANCADO).
-- SEGURO PARA RODAR MÚLTIPLAS VEZES.
-- =============================================================================

BEGIN;

-- =============================================================================
-- 1. HISTÓRICO DIÁRIO DE PREÇO/ESTOQUE POR VARIAÇÃO (formalização)
-- =============================================================================
CREATE TABLE IF NOT EXISTS fato_historico_variacoes (
    model_id BIGINT NOT NULL REFERENCES dim_variacoes(model_id) ON DELETE CASCADE,
    data_registro DATE NOT NULL,
    preco_venda_atual DECIMAL(10,2),
    estoque_shopee INTEGER DEFAULT 0,
    PRIMARY KEY (model_id, data_registro)
);

CREATE INDEX IF NOT EXISTS idx_fato_historico_variacoes_model_data
    ON fato_historico_variacoes (model_id, data_registro DESC);

-- =============================================================================
-- 2. REGISTRO DE LOTES DE IMPORTAÇÃO (idempotência por hash do arquivo)
--    Um mesmo arquivo (hash) importado com o mesmo período nunca é
--    reprocessado por engano; períodos sobrepostos geram aviso na interface.
-- =============================================================================
CREATE TABLE IF NOT EXISTS sys_lotes_importacao (
    id_lote BIGSERIAL PRIMARY KEY,
    modulo VARCHAR(50) NOT NULL,           -- 'TRAFEGO_ORG', 'ADS_AVANCADO', 'VISAO_GERAL'
    nome_arquivo VARCHAR(255) NOT NULL,
    hash_arquivo CHAR(64) NOT NULL,        -- SHA-256 do conteúdo bruto
    periodo_inicio DATE NOT NULL,
    periodo_fim DATE NOT NULL,
    registros_gravados INTEGER NOT NULL DEFAULT 0,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (modulo, hash_arquivo, periodo_inicio, periodo_fim)
);

CREATE INDEX IF NOT EXISTS idx_lotes_modulo_periodo
    ON sys_lotes_importacao (modulo, periodo_fim DESC);

-- =============================================================================
-- 3. VIEWS DE PRÉ-AGREGAÇÃO DIÁRIA (base do futuro refactor do Cérebro IA)
-- =============================================================================

-- Funil completo por item/dia: orgânico + pago em uma única linha.
-- Ads é somado entre tipos de campanha (GMV_MAX + PADRAO) antes do join.
CREATE OR REPLACE VIEW vw_funil_diario_item AS
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
FROM fato_trafego_diario t
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
    GROUP BY item_id, data_registro
) a ON a.item_id = t.item_id AND a.data_registro = t.data;

COMMENT ON VIEW vw_funil_diario_item IS
    'Funil diário unificado (orgânico + ads) por item. Fonte única para janelas 7d/30d do Cérebro IA.';

-- Vendas e cancelamentos por variação/dia. O escrow permanece no nível do
-- pedido (fato_repasse_escrow) para não ratear lucro entre itens de um pedido.
CREATE OR REPLACE VIEW vw_vendas_diarias_variacao AS
SELECT
    i.model_id,
    p.data_hora_criacao::date AS data,
    COUNT(*)                  AS pedidos,
    COUNT(*) FILTER (
        WHERE p.status_pedido IN ('CANCELLED', 'CANCELED', 'CANCELLED_BY_BUYER', 'IN_CANCEL')
    )                         AS pedidos_cancelados,
    COALESCE(SUM(i.quantidade) FILTER (
        WHERE p.status_pedido NOT IN ('CANCELLED', 'CANCELED', 'CANCELLED_BY_BUYER', 'IN_CANCEL')
    ), 0)                     AS unidades_vendidas,
    COALESCE(SUM(i.preco_praticado * i.quantidade) FILTER (
        WHERE p.status_pedido NOT IN ('CANCELLED', 'CANCELED', 'CANCELLED_BY_BUYER', 'IN_CANCEL')
    ), 0)                     AS receita_bruta
FROM fato_itens_pedido i
JOIN fato_pedidos_venda p ON p.order_sn = i.order_sn
GROUP BY i.model_id, p.data_hora_criacao::date;

COMMENT ON VIEW vw_vendas_diarias_variacao IS
    'Vendas diárias por variação, já sem pedidos cancelados. Base das janelas 7d/30d do Cérebro IA.';

-- =============================================================================
-- 4. LIMPEZA: semente órfã do módulo antigo TRAFEGO_ADS (nunca consultado)
-- =============================================================================
DELETE FROM sys_controle_sync
WHERE modulo = 'TRAFEGO_ADS'
  AND registros_afetados = 0
  AND data_inicio_coleta = data_fim_coleta;

COMMIT;

-- =============================================================================
-- VALIDAÇÃO PÓS-MIGRAÇÃO
-- =============================================================================
SELECT
    'Migração 12 aplicada com sucesso!' AS status,
    EXISTS (SELECT 1 FROM information_schema.tables  WHERE table_name = 'fato_historico_variacoes') AS historico_variacoes_ok,
    EXISTS (SELECT 1 FROM information_schema.tables  WHERE table_name = 'sys_lotes_importacao')     AS lotes_importacao_ok,
    EXISTS (SELECT 1 FROM information_schema.views   WHERE table_name = 'vw_funil_diario_item')     AS view_funil_ok,
    EXISTS (SELECT 1 FROM information_schema.views   WHERE table_name = 'vw_vendas_diarias_variacao') AS view_vendas_ok;
