-- =============================================================================
-- MIGRATION 11: CHECKPOINT E RETOMADA DE AUDITORIA IA
-- Persiste cada lote concluído para sobreviver a desligamentos e retomar somente
-- os SKUs pendentes ou alterados dentro da mesma janela analítica.
-- =============================================================================

BEGIN;

ALTER TABLE ia_execucoes_analiticas
    ADD COLUMN IF NOT EXISTS atualizado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;

ALTER TABLE ia_execucoes_analiticas
    DROP CONSTRAINT IF EXISTS ia_execucoes_analiticas_status_check;

ALTER TABLE ia_execucoes_analiticas
    ADD CONSTRAINT ia_execucoes_analiticas_status_check
    CHECK (status IN ('EM_ANDAMENTO', 'CONCLUIDA', 'PARCIAL', 'FALHA'));

CREATE INDEX IF NOT EXISTS idx_ia_execucoes_checkpoint_aberto
    ON ia_execucoes_analiticas (horizonte_dias, fim_janela, atualizado_em DESC)
    WHERE status = 'EM_ANDAMENTO';

COMMIT;

SELECT
    'Migração 11 aplicada com sucesso!' AS status,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'ia_execucoes_analiticas'
          AND column_name = 'atualizado_em'
    ) AS checkpoint_habilitado;
