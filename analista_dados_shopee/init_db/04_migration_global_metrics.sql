-- Migração para métricas globais de loja e métricas importadas por produto
-- Permite armazenar indicadores macro da operação (receita, conversão, ads, etc.)
CREATE TABLE IF NOT EXISTS fato_visao_geral_loja (
    data_registro DATE NOT NULL,
    metric_name VARCHAR(150) NOT NULL,
    metric_value DECIMAL(12,2) NOT NULL,
    fonte VARCHAR(255) NOT NULL,
    PRIMARY KEY (data_registro, metric_name, fonte)
);

CREATE TABLE IF NOT EXISTS fato_metricas_produto_importadas (
    item_id BIGINT NOT NULL REFERENCES dim_produtos(item_id) ON DELETE CASCADE,
    data_registro DATE NOT NULL,
    metric_name VARCHAR(150) NOT NULL,
    metric_value DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    fonte VARCHAR(255) NOT NULL,
    PRIMARY KEY (item_id, data_registro, metric_name, fonte)
);

CREATE INDEX IF NOT EXISTS idx_fato_visao_geral_loja_data
ON fato_visao_geral_loja (data_registro DESC, metric_name);

CREATE INDEX IF NOT EXISTS idx_fato_metricas_produto_importadas_item_data
ON fato_metricas_produto_importadas (item_id, data_registro DESC);

CREATE INDEX IF NOT EXISTS idx_fato_metricas_produto_importadas_metric_data
ON fato_metricas_produto_importadas (metric_name, data_registro DESC);
