-- ==============================================================================
-- MIGRATION 05: SHOPEE ADS AVANÇADO (GMV MAX E PADRÃO)
-- Descrição: Criação da estrutura inteligente para suporte a algoritmos 
--            sem palavras-chave e adição de métricas ricas de conversão.
-- Data: Julho 2026
-- ==============================================================================

BEGIN;

-- =============================================================================
-- 1. CRIAÇÃO DA NOVA TABELA FATO: PERFORMANCE DE ADS
--    Remove a dependência de 'keyword' como chave primária para aceitar 
--    campanhas GMV Max e adiciona o funil completo de conversão.
-- =============================================================================
CREATE TABLE IF NOT EXISTS fato_ads_performance_produto (
    item_id BIGINT NOT NULL REFERENCES dim_produtos(item_id) ON DELETE CASCADE,
    data_registro DATE NOT NULL,
    tipo_campanha VARCHAR(50) NOT NULL, -- Valores esperados: 'GMV_MAX' ou 'PADRAO'
    nome_anuncio VARCHAR(255),
    
    -- Topo de Funil
    impressoes INTEGER DEFAULT 0,
    cliques INTEGER DEFAULT 0,
    investimento DECIMAL(12,2) DEFAULT 0.0,
    
    -- Fundo de Funil e Inteligência
    vendas_gmv DECIMAL(12,2) DEFAULT 0.0,
    adicoes_carrinho INTEGER DEFAULT 0,
    conversoes INTEGER DEFAULT 0,
    itens_vendidos INTEGER DEFAULT 0,
    
    -- Taxas de Performance (Armazenadas para não recalcular a cada query)
    roas DECIMAL(12,2) DEFAULT 0.0,
    acos DECIMAL(12,2) DEFAULT 0.0,
    
    -- A combinação de Produto + Dia + Tipo de Campanha garante a idempotência
    PRIMARY KEY (item_id, data_registro, tipo_campanha)
);

-- =============================================================================
-- 2. ÍNDICES DE PERFORMANCE (OTIMIZAÇÃO DO QUERY PLANNER)
--    Garante que a IA consiga cruzar Ads vs Orgânico em milissegundos.
-- =============================================================================
CREATE INDEX IF NOT EXISTS idx_ads_perf_item_data 
    ON fato_ads_performance_produto(item_id, data_registro DESC);

CREATE INDEX IF NOT EXISTS idx_ads_perf_tipo_campanha 
    ON fato_ads_performance_produto(tipo_campanha, data_registro DESC);

-- =============================================================================
-- 3. SEMENTE DE CONTROLE DE SINCRONIZAÇÃO
--    Impede erros no aplicativo Python quando ele tentar buscar a 
--    "última data de sincronização" antes de você subir o primeiro arquivo.
-- =============================================================================
INSERT INTO sys_controle_sync (modulo, data_inicio_coleta, data_fim_coleta, status, registros_afetados)
SELECT 'ADS_AVANCADO', '2026-01-26 00:00:00', '2026-01-26 00:00:00', 'SUCESSO', 0
WHERE NOT EXISTS (
    SELECT 1 FROM sys_controle_sync WHERE modulo = 'ADS_AVANCADO'
);

COMMIT;

-- =============================================================================
-- 4. VALIDAÇÃO DA MIGRAÇÃO (RODA FORA DA TRANSAÇÃO PARA FEEDBACK VISUAL)
-- =============================================================================
SELECT
    'Migração 05 aplicada com sucesso!' AS status,
    EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_name = 'fato_ads_performance_produto'
    ) AS tabela_ads_criada,
    (
        SELECT COUNT(*) FROM sys_controle_sync WHERE modulo = 'ADS_AVANCADO'
    ) AS sementes_ads_avancado;