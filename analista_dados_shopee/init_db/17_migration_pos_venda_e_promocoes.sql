-- =============================================================================
-- MIGRATION 17: PÓS-VENDA E PROMOÇÕES VIA API (sondagem ao vivo de 18/07/2026)
-- Descrição:
--   1. Campos extras do pedido (get_order_detail já os devolve para este app):
--      comprador (recompra/LTV), pay_time/ship_by_date/pickup_done_time (tempo
--      de preparo REAL vs prazo — ataque direto ao late shipment da conta),
--      frete real, transportadora e entrega (via get_tracking_info).
--   2. Promoções vigentes (desconto, combo, add-on, flash sale): sem elas, uma
--      queda de preço por promoção é lida como reprecificação e contamina a
--      elasticidade do Cérebro.
--   3. Devoluções com motivo (get_return_list): sinal de qualidade por produto.
-- SEGURO PARA RODAR MÚLTIPLAS VEZES.
-- =============================================================================

BEGIN;

-- =============================================================================
-- 1. CAMPOS PÓS-VENDA NO PEDIDO
-- =============================================================================
ALTER TABLE fato_pedidos_venda
    ADD COLUMN IF NOT EXISTS buyer_user_id BIGINT,
    ADD COLUMN IF NOT EXISTS buyer_username VARCHAR(80),
    ADD COLUMN IF NOT EXISTS pay_time TIMESTAMP,
    ADD COLUMN IF NOT EXISTS ship_by_date TIMESTAMP,
    ADD COLUMN IF NOT EXISTS pickup_done_time TIMESTAMP,
    ADD COLUMN IF NOT EXISTS frete_real DECIMAL(10,2),
    ADD COLUMN IF NOT EXISTS shipping_carrier VARCHAR(80),
    ADD COLUMN IF NOT EXISTS logistics_status VARCHAR(40),
    ADD COLUMN IF NOT EXISTS delivered_time TIMESTAMP;

-- Recompra: "este comprador já comprou antes?" é um EXISTS por (comprador, data)
CREATE INDEX IF NOT EXISTS idx_pedidos_buyer_data
    ON fato_pedidos_venda (buyer_user_id, data_hora_criacao)
    WHERE buyer_user_id IS NOT NULL;

-- =============================================================================
-- 2. PROMOÇÕES DA LOJA (4 famílias, com os itens cobertos por cada uma)
-- =============================================================================
CREATE TABLE IF NOT EXISTS fato_promocoes_shopee (
    tipo VARCHAR(20) NOT NULL,            -- DESCONTO | COMBO | ADD_ON | FLASH_SALE
    id_promocao BIGINT NOT NULL,
    nome VARCHAR(255),
    status VARCHAR(30),                   -- upcoming | ongoing | expired (derivado do período)
    inicio TIMESTAMP,
    fim TIMESTAMP,
    atualizado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tipo, id_promocao)
);

CREATE TABLE IF NOT EXISTS map_promocao_itens (
    tipo VARCHAR(20) NOT NULL,
    id_promocao BIGINT NOT NULL,
    item_id BIGINT NOT NULL,
    model_id BIGINT NOT NULL DEFAULT 0,   -- 0 = anúncio inteiro
    preco_promocional DECIMAL(10,2),
    PRIMARY KEY (tipo, id_promocao, item_id, model_id),
    FOREIGN KEY (tipo, id_promocao)
        REFERENCES fato_promocoes_shopee (tipo, id_promocao) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_promo_itens_item ON map_promocao_itens (item_id);

-- =============================================================================
-- 3. DEVOLUÇÕES COM MOTIVO
-- =============================================================================
CREATE TABLE IF NOT EXISTS fato_devolucoes (
    return_sn VARCHAR(50) PRIMARY KEY,
    order_sn VARCHAR(50),                 -- sem FK: a devolução pode referir pedido fora da janela do DW
    status VARCHAR(40),
    motivo VARCHAR(120),
    motivo_texto TEXT,
    valor_reembolso DECIMAL(10,2),
    criado_em_shopee TIMESTAMP,
    atualizado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_devolucoes_order ON fato_devolucoes (order_sn);
CREATE INDEX IF NOT EXISTS idx_devolucoes_data ON fato_devolucoes (criado_em_shopee);

CREATE TABLE IF NOT EXISTS map_devolucao_itens (
    return_sn VARCHAR(50) NOT NULL REFERENCES fato_devolucoes(return_sn) ON DELETE CASCADE,
    item_id BIGINT NOT NULL,
    model_id BIGINT NOT NULL DEFAULT 0,
    quantidade INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (return_sn, item_id, model_id)
);

CREATE INDEX IF NOT EXISTS idx_devolucao_itens_item ON map_devolucao_itens (item_id);

COMMIT;

-- =============================================================================
-- VALIDAÇÃO PÓS-MIGRAÇÃO
-- =============================================================================
SELECT
    'Migração 17 aplicada com sucesso!' AS status,
    EXISTS (SELECT 1 FROM information_schema.columns
            WHERE table_name = 'fato_pedidos_venda' AND column_name = 'buyer_user_id')   AS pedidos_pos_venda_ok,
    EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'fato_promocoes_shopee') AS promocoes_ok,
    EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'fato_devolucoes')       AS devolucoes_ok;
