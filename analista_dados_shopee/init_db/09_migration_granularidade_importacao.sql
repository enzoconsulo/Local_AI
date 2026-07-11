-- =============================================================================
-- MIGRATION 09: GRANULARIDADE E CONFIABILIDADE DA ORIGEM IMPORTADA
-- Descrição: distingue observações diárias reais de arquivos agregados em período.
-- =============================================================================

BEGIN;

ALTER TABLE fato_trafego_diario
    ADD COLUMN IF NOT EXISTS granularidade_origem VARCHAR(20) NOT NULL DEFAULT 'DESCONHECIDA';

ALTER TABLE fato_ads_performance_produto
    ADD COLUMN IF NOT EXISTS granularidade_origem VARCHAR(20) NOT NULL DEFAULT 'DESCONHECIDA';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_trafego_granularidade_origem') THEN
        ALTER TABLE fato_trafego_diario
            ADD CONSTRAINT ck_trafego_granularidade_origem
            CHECK (granularidade_origem IN ('DIARIA', 'AGREGADA_PERIODO', 'DESCONHECIDA'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_ads_granularidade_origem') THEN
        ALTER TABLE fato_ads_performance_produto
            ADD CONSTRAINT ck_ads_granularidade_origem
            CHECK (granularidade_origem IN ('DIARIA', 'AGREGADA_PERIODO', 'DESCONHECIDA'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_trafego_granularidade_data
    ON fato_trafego_diario(granularidade_origem, data DESC);

CREATE INDEX IF NOT EXISTS idx_ads_granularidade_data
    ON fato_ads_performance_produto(granularidade_origem, data_registro DESC);

COMMIT;

SELECT
    'Migração 09 aplicada com sucesso!' AS status,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'fato_trafego_diario' AND column_name = 'granularidade_origem'
    ) AS trafego_granularidade_criada,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'fato_ads_performance_produto' AND column_name = 'granularidade_origem'
    ) AS ads_granularidade_criada;
