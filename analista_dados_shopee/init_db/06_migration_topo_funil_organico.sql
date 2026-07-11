-- ==============================================================================
-- MIGRATION 06: TOPO DE FUNIL ORGÂNICO
-- Descrição: Adição das métricas de Impressões e Cliques na tabela de tráfego 
--            diário para permitir o cálculo de CTR pelo Cérebro IA.
-- Data: Julho 2026
-- ==============================================================================

BEGIN;

-- =============================================================================
-- 1. ALTERAÇÃO DA TABELA FATO: TRÁFEGO DIÁRIO
--    Adiciona as colunas necessárias sem apagar os dados que já existem.
-- =============================================================================
ALTER TABLE fato_trafego_diario
ADD COLUMN IF NOT EXISTS impressoes INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS cliques INTEGER DEFAULT 0;

COMMIT;

-- =============================================================================
-- 2. VALIDAÇÃO DA MIGRAÇÃO (RODA FORA DA TRANSAÇÃO)
-- =============================================================================
SELECT
    'Migração 06 aplicada com sucesso!' AS status,
    EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'fato_trafego_diario' AND column_name = 'impressoes'
    ) AS coluna_impressoes_criada,
    EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'fato_trafego_diario' AND column_name = 'cliques'
    ) AS coluna_cliques_criada;