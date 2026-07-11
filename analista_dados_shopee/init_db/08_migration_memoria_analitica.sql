-- =============================================================================
-- MIGRATION 08: MEMÓRIA ANALÍTICA PERSISTENTE E AVALIAÇÃO DE AÇÕES
-- Descrição: preserva cada auditoria, seus snapshots por variação e mede o
-- resultado observado após ações executadas. Não duplica fatos operacionais.
-- Data: Julho 2026
-- =============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Uma execução representa uma auditoria completa de um único horizonte.
CREATE TABLE IF NOT EXISTS ia_execucoes_analiticas (
    id_execucao UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    criado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    horizonte_dias SMALLINT NOT NULL CHECK (horizonte_dias IN (7, 30)),
    inicio_janela DATE NOT NULL,
    fim_janela DATE NOT NULL,
    modelo_ia VARCHAR(150) NOT NULL DEFAULT 'cerebro-dados',
    versao_prompt VARCHAR(50) NOT NULL DEFAULT 'v1',
    total_variacoes INTEGER NOT NULL DEFAULT 0 CHECK (total_variacoes >= 0),
    cobertura_dados JSONB NOT NULL DEFAULT '{}'::jsonb,
    resumo_executivo JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(20) NOT NULL DEFAULT 'CONCLUIDA'
        CHECK (status IN ('CONCLUIDA', 'PARCIAL', 'FALHA'))
);

-- Snapshot imutável: fatos observados, projeção e parecer recebidos naquele instante.
CREATE TABLE IF NOT EXISTS ia_snapshots_variacao (
    id_snapshot BIGSERIAL PRIMARY KEY,
    id_execucao UUID NOT NULL REFERENCES ia_execucoes_analiticas(id_execucao) ON DELETE CASCADE,
    item_id BIGINT NOT NULL REFERENCES dim_produtos(item_id) ON DELETE CASCADE,
    model_id BIGINT NOT NULL REFERENCES dim_variacoes(model_id) ON DELETE CASCADE,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    score_urgencia SMALLINT NOT NULL DEFAULT 0 CHECK (score_urgencia BETWEEN 0 AND 100),
    qualidade_evidencia VARCHAR(20),
    tipo_acao_recomendada VARCHAR(50),
    metricas_observadas JSONB NOT NULL DEFAULT '{}'::jsonb,
    previsoes JSONB NOT NULL DEFAULT '{}'::jsonb,
    recomendacao JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (id_execucao, model_id)
);

-- Liga o log operacional existente à auditoria que originou a decisão.
ALTER TABLE log_acoes_shopee
    ADD COLUMN IF NOT EXISTS id_execucao_origem UUID
        REFERENCES ia_execucoes_analiticas(id_execucao) ON DELETE SET NULL;

-- Resultado observado após maturação mínima. Não afirma causalidade: registra comparação.
CREATE TABLE IF NOT EXISTS ia_avaliacoes_acoes (
    id_avaliacao BIGSERIAL PRIMARY KEY,
    id_log BIGINT NOT NULL UNIQUE REFERENCES log_acoes_shopee(id_log) ON DELETE CASCADE,
    id_execucao_origem UUID REFERENCES ia_execucoes_analiticas(id_execucao) ON DELETE SET NULL,
    item_id BIGINT NOT NULL REFERENCES dim_produtos(item_id) ON DELETE CASCADE,
    model_id BIGINT REFERENCES dim_variacoes(model_id) ON DELETE SET NULL,
    horizonte_observacao_dias SMALLINT NOT NULL CHECK (horizonte_observacao_dias IN (7, 30)),
    data_inicio_observacao TIMESTAMPTZ NOT NULL,
    data_fim_observacao TIMESTAMPTZ NOT NULL,
    avaliado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    baseline JSONB NOT NULL DEFAULT '{}'::jsonb,
    previsto JSONB NOT NULL DEFAULT '{}'::jsonb,
    observado JSONB NOT NULL DEFAULT '{}'::jsonb,
    comparacao JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(20) NOT NULL DEFAULT 'AVALIADA'
        CHECK (status IN ('AVALIADA', 'DADOS_INSUFICIENTES')),
    nota_metodologica TEXT NOT NULL DEFAULT
        'Comparação observacional: não prova causalidade, pois preço, tráfego, ads e sazonalidade podem variar simultaneamente.'
);

-- Índices das consultas críticas do Cérebro: última estratégia mensal e ações pendentes.
CREATE INDEX IF NOT EXISTS idx_ia_execucoes_horizonte_criado
    ON ia_execucoes_analiticas(horizonte_dias, criado_em DESC)
    WHERE status = 'CONCLUIDA';

CREATE INDEX IF NOT EXISTS idx_ia_snapshots_model_execucao
    ON ia_snapshots_variacao(model_id, id_execucao DESC);

CREATE INDEX IF NOT EXISTS idx_ia_snapshots_item_execucao
    ON ia_snapshots_variacao(item_id, id_execucao DESC);

CREATE INDEX IF NOT EXISTS idx_log_acoes_execucao_origem
    ON log_acoes_shopee(id_execucao_origem)
    WHERE id_execucao_origem IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ia_avaliacoes_model_avaliado
    ON ia_avaliacoes_acoes(model_id, avaliado_em DESC);

COMMIT;

-- =============================================================================
-- VALIDAÇÃO PÓS-MIGRAÇÃO
-- =============================================================================
SELECT
    'Migração 08 aplicada com sucesso!' AS status,
    EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'ia_execucoes_analiticas') AS execucoes_criada,
    EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'ia_snapshots_variacao') AS snapshots_criada,
    EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'ia_avaliacoes_acoes') AS avaliacoes_criada,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'log_acoes_shopee' AND column_name = 'id_execucao_origem'
    ) AS log_vinculado;
