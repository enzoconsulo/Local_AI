-- =============================================================================
-- MIGRATION 10: CACHE SEMÂNTICO DE AUDITORIAS
-- Evita nova inferência quando os fatos relevantes de um SKU não mudaram.
-- =============================================================================

BEGIN;

ALTER TABLE ia_snapshots_variacao
    ADD COLUMN IF NOT EXISTS fingerprint_entrada CHAR(64);

CREATE INDEX IF NOT EXISTS idx_ia_snapshot_fingerprint_modelo
    ON ia_snapshots_variacao(model_id, fingerprint_entrada, criado_em DESC)
    WHERE fingerprint_entrada IS NOT NULL;

COMMIT;

SELECT
    'Migração 10 aplicada com sucesso!' AS status,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'ia_snapshots_variacao' AND column_name = 'fingerprint_entrada'
    ) AS fingerprint_criado;
