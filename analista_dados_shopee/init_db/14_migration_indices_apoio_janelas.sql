-- =============================================================================
-- MIGRATION 14: ÍNDICES DE APOIO ÀS JANELAS DO DOSSIÊ
-- Descrição:
--   O dossiê do Cérebro IA passou a ler fato_historico_variacoes e
--   fato_metricas_produto_importadas por janela de datas (35 e 7 dias).
--   Os índices existentes começam por model_id/item_id e não atendem filtros
--   somente por data; estes índices mantêm as CTEs limitadas pelo tamanho da
--   janela (e não pelo tamanho do histórico) conforme o banco cresce.
-- SEGURO PARA RODAR MÚLTIPLAS VEZES.
-- =============================================================================

BEGIN;

CREATE INDEX IF NOT EXISTS idx_historico_variacoes_data
    ON fato_historico_variacoes (data_registro DESC);

CREATE INDEX IF NOT EXISTS idx_metricas_importadas_data
    ON fato_metricas_produto_importadas (data_registro DESC);

COMMIT;

ANALYZE fato_historico_variacoes;
ANALYZE fato_metricas_produto_importadas;

-- =============================================================================
-- VALIDAÇÃO PÓS-MIGRAÇÃO
-- =============================================================================
SELECT
    'Migração 14 aplicada com sucesso!' AS status,
    EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE tablename = 'fato_historico_variacoes' AND indexname = 'idx_historico_variacoes_data'
    ) AS indice_historico_ok,
    EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE tablename = 'fato_metricas_produto_importadas' AND indexname = 'idx_metricas_importadas_data'
    ) AS indice_metricas_ok;
