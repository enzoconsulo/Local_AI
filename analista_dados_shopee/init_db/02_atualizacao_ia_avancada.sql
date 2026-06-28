-- ==============================================================================
-- MIGRATION 02: MÉTRICAS AVANÇADAS PARA IA, ELASTICIDADE E LOGÍSTICA
-- Data: Junho 2026
-- ==============================================================================

-- 1. ADIÇÕES NA TABELA DE PRODUTOS E VARIAÇÕES
-- Controla a reputação do anúncio, regras de envio e gatilhos de promoção.
ALTER TABLE dim_produtos 
ADD COLUMN nota_media_estrelas DECIMAL(3,2) DEFAULT 0.00,
ADD COLUMN total_avaliacoes INTEGER DEFAULT 0,
ADD COLUMN dias_pre_encomenda INTEGER DEFAULT 3,
ADD COLUMN likes_count INTEGER DEFAULT 0;

ALTER TABLE dim_variacoes 
ADD COLUMN estoque_shopee INTEGER DEFAULT 0;

-- 2. ADIÇÕES NA ENGENHARIA E MATERIAIS (A Realidade da Impressão 3D)
-- Taxa de vezes que a impressão falha ou descola da mesa (refugo).
ALTER TABLE map_engenharia_produto 
ADD COLUMN taxa_perda_percentual DECIMAL(5,2) DEFAULT 0.00;

-- Controle de estoque físico na prateleira.
ALTER TABLE dim_materiais 
ADD COLUMN estoque_atual DECIMAL(10,2) DEFAULT 0.00;

-- 3. ADIÇÕES NOS PEDIDOS (O Custo Oculto que destrói lojas)
-- Motivo exato caso o cliente devolva ou cancele.
ALTER TABLE fato_pedidos_venda 
ADD COLUMN motivo_cancelamento_devolucao VARCHAR(255);

-- O valor que a Shopee lhe arranca do bolso pelo frete reverso.
ALTER TABLE fato_repasse_escrow 
ADD COLUMN custo_frete_reverso DECIMAL(10,2) DEFAULT 0.00;

-- 4. NOVA TABELA: HISTÓRICO DE PROMOÇÕES (Para a IA separar orgânico de oferta)
CREATE TABLE fato_promocoes_ativas (
    id_registro SERIAL PRIMARY KEY,
    model_id BIGINT REFERENCES dim_variacoes(model_id) ON DELETE CASCADE,
    nome_promocao VARCHAR(255),
    preco_promocional DECIMAL(10,2),
    data_inicio TIMESTAMP,
    data_fim TIMESTAMP
);