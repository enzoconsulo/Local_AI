-- ==============================================================================
-- MIGRATION 03: RASTREAMENTO POR VARIAÇÃO + ÍNDICES DE PERFORMANCE
-- Data: Junho 2026
-- ==============================================================================
-- Como executar (escolha um):
--   Via psql: psql -U admin_shopee -d shopee_dw -f 03_migration_performance.sql
--   Via pgAdmin: Abrir Query Tool → colar este conteúdo → F5
--
-- SEGURO PARA RODAR MÚLTIPLAS VEZES: todos os comandos usam IF NOT EXISTS
-- ==============================================================================

BEGIN;

-- =============================================================================
-- 1. RASTREAMENTO POR VARIAÇÃO (model_id) NO LOG DE AÇÕES
--    Fix #7: a IA agora lembra de ações por VARIAÇÃO (ex: cor Vermelho),
--    não pelo produto inteiro. Registros antigos (sem model_id) ficam com NULL
--    e são excluídos da memória da IA — comportamento correto, pois eles
--    "vazavam" para as variações-irmãs.
-- =============================================================================
ALTER TABLE log_acoes_shopee
    ADD COLUMN IF NOT EXISTS model_id BIGINT REFERENCES dim_variacoes(model_id);

-- =============================================================================
-- 2. ÍNDICES DO LOG DE AÇÕES
--    Consultas da CTE memoria_ia na query do dossiê.
-- =============================================================================
CREATE INDEX IF NOT EXISTS idx_log_model_data
    ON log_acoes_shopee(model_id, data_aplicacao DESC)
    WHERE model_id IS NOT NULL;          -- índice parcial: só registros novos (mais enxuto)

CREATE INDEX IF NOT EXISTS idx_log_item_data
    ON log_acoes_shopee(item_id, data_aplicacao DESC);

CREATE INDEX IF NOT EXISTS idx_log_status_data
    ON log_acoes_shopee(status_api, data_aplicacao DESC);

-- =============================================================================
-- 3. ÍNDICES DE PERFORMANCE PARA O DOSSIÊ DA IA
--    A query principal (gerar_dossie_produtos_com_memoria) faz 9 CTEs com
--    múltiplos JOINs e filtros de data. Cada índice abaixo elimina um seq scan.
-- =============================================================================

-- Joins entre fato_itens_pedido e suas tabelas pai
CREATE INDEX IF NOT EXISTS idx_itens_model
    ON fato_itens_pedido(model_id);
CREATE INDEX IF NOT EXISTS idx_itens_order
    ON fato_itens_pedido(order_sn);

-- Filtro de data nos pedidos (WHERE p.data_hora_criacao >= ...)
CREATE INDEX IF NOT EXISTS idx_pedidos_data
    ON fato_pedidos_venda(data_hora_criacao DESC);

-- Join entre repasse e pedidos
CREATE INDEX IF NOT EXISTS idx_repasse_order
    ON fato_repasse_escrow(order_sn);

-- Filtros de data no tráfego e ads
CREATE INDEX IF NOT EXISTS idx_trafego_data_item
    ON fato_trafego_diario(data DESC, item_id);
CREATE INDEX IF NOT EXISTS idx_ads_data_item
    ON fato_ads_palavras_chave(data DESC, item_id);

-- JOINs de variações e engenharia
CREATE INDEX IF NOT EXISTS idx_variacoes_item
    ON dim_variacoes(item_id);
CREATE INDEX IF NOT EXISTS idx_engenharia_material
    ON map_engenharia_produto(id_material);
CREATE INDEX IF NOT EXISTS idx_engenharia_maquina
    ON map_engenharia_produto(id_maquina);

-- Filtro de status em produtos (WHERE status_shopee = 'NORMAL')
CREATE INDEX IF NOT EXISTS idx_produtos_status
    ON dim_produtos(status_shopee)
    WHERE status_shopee = 'NORMAL';     -- índice parcial: só produtos ativos

-- =============================================================================
-- 4. ÍNDICE PARA SINCRONIZAÇÃO DELTA
--    Consulta de "qual foi a última sync bem-sucedida deste módulo?"
-- =============================================================================
CREATE INDEX IF NOT EXISTS idx_sync_modulo_status
    ON sys_controle_sync(modulo, status, data_fim_coleta DESC);

-- =============================================================================
-- 5. VIEW ANALÍTICA: SAÚDE POR VARIAÇÃO
--    Usada pelo Chat Assistente e por queries ad-hoc no pgAdmin.
--    Não é materializada para garantir dados sempre frescos.
--    Exposta no SCHEMA_DO_BANCO do arquivo 4___Chat_Assistente.py também.
-- =============================================================================
CREATE OR REPLACE VIEW vw_saude_produto AS
SELECT
    p.item_id,
    v.model_id,
    p.nome_atual,
    v.nome_variacao,
    v.preco_venda_atual,
    p.nota_media_estrelas,
    p.likes_count,
    v.estoque_shopee,
    p.status_shopee,

    -- Vendas e receita nos últimos 7 dias (apenas pedidos com escrow liberado)
    COALESCE(SUM(i.quantidade)
        FILTER (WHERE ped.data_hora_criacao >= CURRENT_DATE - INTERVAL '7 days'
                  AND r.order_sn IS NOT NULL), 0)               AS vendas_7d,
    COALESCE(SUM(r.lucro_liquido_absoluto)
        FILTER (WHERE ped.data_hora_criacao >= CURRENT_DATE - INTERVAL '7 days'), 0)
                                                                AS receita_liquida_7d,

    -- Custo de fabricação (com refugo)
    ROUND((
        (CASE WHEN mat.unidade_medida = 'kg'
              THEN (eng.peso_gramas / 1000.0) ELSE eng.peso_gramas END
         * mat.custo_por_unidade)
        + (eng.tempo_impressao_minutos * maq.custo_energia_hora / 60.0)
        + COALESCE(eng.custo_embalagem, 0)
    ) * (1 + COALESCE(eng.taxa_perda_percentual, 0) / 100.0), 2)
                                                                AS custo_fabricacao,

    -- Última ação da IA para esta variação
    ult.tipo_acao                                               AS ultima_acao_ia,
    ult.data_aplicacao                                          AS data_ultima_acao

FROM dim_produtos p
JOIN dim_variacoes v              ON p.item_id   = v.item_id
LEFT JOIN map_engenharia_produto eng ON v.model_id = eng.model_id
LEFT JOIN dim_materiais mat       ON eng.id_material = mat.id_material
LEFT JOIN dim_maquinas maq        ON eng.id_maquina  = maq.id_maquina
LEFT JOIN fato_itens_pedido i     ON v.model_id   = i.model_id
LEFT JOIN fato_pedidos_venda ped  ON i.order_sn   = ped.order_sn
LEFT JOIN fato_repasse_escrow r   ON ped.order_sn = r.order_sn
-- Subquery para pegar apenas a última ação por variação
LEFT JOIN LATERAL (
    SELECT tipo_acao, data_aplicacao
    FROM   log_acoes_shopee
    WHERE  model_id = v.model_id AND status_api = 'SUCESSO'
    ORDER  BY data_aplicacao DESC
    LIMIT  1
) ult ON TRUE
WHERE p.status_shopee = 'NORMAL'
GROUP BY
    p.item_id, v.model_id, p.nome_atual, v.nome_variacao,
    v.preco_venda_atual, p.nota_media_estrelas, p.likes_count,
    v.estoque_shopee, p.status_shopee,
    eng.peso_gramas, eng.tempo_impressao_minutos, eng.custo_embalagem, eng.taxa_perda_percentual,
    mat.custo_por_unidade, mat.unidade_medida,
    maq.custo_energia_hora,
    ult.tipo_acao, ult.data_aplicacao;

COMMENT ON VIEW vw_saude_produto IS
    'KPIs por variação de produto (tempo real). '
    'Adicione ao SCHEMA_DO_BANCO em 4___Chat_Assistente.py para o Chat poder consultar.';

-- =============================================================================
-- 6. ATUALIZA O SCHEMA DO CHAT ASSISTENTE (comentário de lembrete)
--    Adicione a linha abaixo ao SCHEMA_DO_BANCO em 4___Chat_Assistente.py:
--    10. vw_saude_produto (item_id, model_id, nome_atual, nome_variacao,
--        preco_venda_atual, nota_media_estrelas, likes_count, estoque_shopee,
--        vendas_7d, receita_liquida_7d, custo_fabricacao, ultima_acao_ia)
-- =============================================================================

COMMIT;

-- Relatório de confirmação (roda fora da transação para sempre exibir)
SELECT
    'Migração 03 aplicada com sucesso!' AS resultado,
    (
        SELECT COUNT(*)
        FROM   pg_indexes
        WHERE  tablename IN (
            'log_acoes_shopee', 'fato_itens_pedido', 'fato_pedidos_venda',
            'fato_repasse_escrow', 'fato_trafego_diario', 'fato_ads_palavras_chave',
            'dim_variacoes', 'map_engenharia_produto', 'dim_produtos', 'sys_controle_sync'
        )
    ) AS total_indices_no_banco,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE  table_name = 'log_acoes_shopee' AND column_name = 'model_id'
    ) AS coluna_model_id_existe,
    EXISTS (
        SELECT 1 FROM information_schema.views WHERE table_name = 'vw_saude_produto'
    ) AS view_saude_criada;
