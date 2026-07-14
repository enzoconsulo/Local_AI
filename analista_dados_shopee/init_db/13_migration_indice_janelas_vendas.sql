-- =============================================================================
-- MIGRATION 13: ÍNDICE DE EXPRESSÃO PARA AS JANELAS DE VENDAS
-- Descrição:
--   A vw_vendas_diarias_variacao agrupa por data_hora_criacao::date e o
--   Cérebro filtra "data >= CURRENT_DATE - 30". O predicado é empurrado para
--   dentro da view como (data_hora_criacao::date >= ...), que um índice B-tree
--   comum sobre data_hora_criacao NÃO atende (a expressão com cast não é
--   sargável). Este índice de expressão elimina o seq scan de
--   fato_pedidos_venda em toda auditoria, mantendo o custo estável conforme
--   o histórico de pedidos cresce.
-- SEGURO PARA RODAR MÚLTIPLAS VEZES.
-- =============================================================================

BEGIN;

CREATE INDEX IF NOT EXISTS idx_pedidos_data_date
    ON fato_pedidos_venda ((data_hora_criacao::date) DESC);

COMMIT;

ANALYZE fato_pedidos_venda;

-- =============================================================================
-- VALIDAÇÃO PÓS-MIGRAÇÃO
-- =============================================================================
SELECT
    'Migração 13 aplicada com sucesso!' AS status,
    EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE tablename = 'fato_pedidos_venda' AND indexname = 'idx_pedidos_data_date'
    ) AS indice_expressao_criado;
