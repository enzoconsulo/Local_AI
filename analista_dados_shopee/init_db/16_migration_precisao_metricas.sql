-- ==============================================================================
-- MIGRATION 16: PRECISÃO DE MÉTRICAS + SANEAMENTO DE uf_destino
-- Descrição:
--   1. metric_value passa de DECIMAL(12,2) para DECIMAL(14,4) nas duas tabelas
--      de métricas. O código sempre gravou taxas com 4 casas (importador) e a
--      saúde da conta grava rates que podem ser < 0,01 (ex.: late_shipment_rate
--      0,004) — com 2 casas o banco arredondava para 0,00 e um indicador fora
--      da meta aparecia como "dentro da meta".
--   2. uf_destino recebia order.region da API ("BR" — o PAÍS, nunca a UF) por
--      bug do sync de pedidos. 'BR' não carrega informação: vira NULL
--      (= desconhecido). O sync corrigido passa a gravar a UF real vinda de
--      recipient_address.state.
-- SEGURO PARA RODAR MÚLTIPLAS VEZES.
-- ==============================================================================

BEGIN;

ALTER TABLE fato_visao_geral_loja
    ALTER COLUMN metric_value TYPE DECIMAL(14,4);

ALTER TABLE fato_metricas_produto_importadas
    ALTER COLUMN metric_value TYPE DECIMAL(14,4);

UPDATE fato_pedidos_venda
SET uf_destino = NULL
WHERE uf_destino = 'BR';

COMMIT;

-- =============================================================================
-- VALIDAÇÃO PÓS-MIGRAÇÃO
-- =============================================================================
SELECT
    'Migração 16 aplicada com sucesso!' AS status,
    (SELECT numeric_scale FROM information_schema.columns
     WHERE table_schema = 'public' AND table_name = 'fato_visao_geral_loja'
       AND column_name = 'metric_value') AS escala_visao_geral,
    (SELECT numeric_scale FROM information_schema.columns
     WHERE table_schema = 'public' AND table_name = 'fato_metricas_produto_importadas'
       AND column_name = 'metric_value') AS escala_metricas_produto,
    NOT EXISTS (SELECT 1 FROM fato_pedidos_venda WHERE uf_destino = 'BR') AS uf_saneada;
