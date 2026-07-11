-- ==============================================================================
-- MIGRATION 07: SANEAMENTO E TRAVA DE IDEMPOTÊNCIA (TRÁFEGO)
-- Descrição: Remove duplicidades históricas e adiciona a Constraint UNIQUE
--            necessária para que o 'ON CONFLICT DO UPDATE' funcione no Python.
-- Data: Julho 2026
-- ==============================================================================

BEGIN;

-- 1. SANEAMENTO (Deduplicação Segura)
-- Identifica se você subiu a mesma planilha 2x no passado e apagará os clones,
-- mantendo sempre o id_registro mais recente (o dado mais atualizado).
DELETE FROM fato_trafego_diario
WHERE id_registro NOT IN (
    SELECT MAX(id_registro)
    FROM fato_trafego_diario
    GROUP BY item_id, data
);

-- 2. CRIAÇÃO DA TRAVA (Armadura de Idempotência)
-- Agora que temos certeza que não há duplicatas, aplicamos a trava.
-- O "IF NOT EXISTS" não existe para ADD CONSTRAINT em versões mais antigas do Postgres,
-- então usamos um bloco DO anônimo para ser à prova de falhas.
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uk_trafego_item_data'
    ) THEN
        ALTER TABLE fato_trafego_diario 
        ADD CONSTRAINT uk_trafego_item_data UNIQUE (item_id, data);
    END IF;
END $$;

COMMIT;

-- 3. VALIDAÇÃO DA MIGRAÇÃO
SELECT
    'Migração 07 aplicada com sucesso!' AS status,
    EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uk_trafego_item_data'
    ) AS trava_idempotencia_criada;