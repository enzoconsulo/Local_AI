-- Módulo 1: Custos e Manufatura
CREATE TABLE dim_materiais (
    id_material SERIAL PRIMARY KEY,
    nome VARCHAR(100) NOT NULL,
    tipo VARCHAR(50) NOT NULL, 
    custo_por_unidade DECIMAL(10,4) NOT NULL, 
    unidade_medida VARCHAR(20) NOT NULL, 
    data_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE dim_maquinas (
    id_maquina SERIAL PRIMARY KEY,
    nome_modelo VARCHAR(100) NOT NULL,
    custo_energia_hora DECIMAL(10,4) NOT NULL, 
    status VARCHAR(20) DEFAULT 'Ativa'
);

-- Módulo 2: Catálogo e Engenharia 
CREATE TABLE dim_produtos (
    item_id BIGINT PRIMARY KEY, 
    nome_atual VARCHAR(255) NOT NULL,
    category_id BIGINT,
    status_shopee VARCHAR(50),
    data_criacao TIMESTAMP
);

CREATE TABLE dim_variacoes (
    model_id BIGINT PRIMARY KEY, 
    item_id BIGINT REFERENCES dim_produtos(item_id) ON DELETE CASCADE,
    nome_variacao VARCHAR(255) NOT NULL,
    sku_variacao VARCHAR(100),
    preco_venda_atual DECIMAL(10,2)
);

CREATE TABLE map_engenharia_produto (
    id_mapeamento SERIAL PRIMARY KEY,
    model_id BIGINT UNIQUE REFERENCES dim_variacoes(model_id) ON DELETE CASCADE,
    id_material INTEGER REFERENCES dim_materiais(id_material),
    id_maquina INTEGER REFERENCES dim_maquinas(id_maquina),
    peso_gramas DECIMAL(10,2) NOT NULL,
    tempo_impressao_minutos INTEGER NOT NULL,
    custo_embalagem DECIMAL(10,2) DEFAULT 0.00,
    data_mapeamento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Módulo 3: Vendas, Escrow e Tráfego
CREATE TABLE fato_pedidos_venda (
    order_sn VARCHAR(50) PRIMARY KEY,
    data_hora_criacao TIMESTAMP NOT NULL,
    uf_destino CHAR(2),
    status_pedido VARCHAR(50)
);

CREATE TABLE fato_itens_pedido (
    id_registro SERIAL PRIMARY KEY,
    order_sn VARCHAR(50) REFERENCES fato_pedidos_venda(order_sn),
    model_id BIGINT REFERENCES dim_variacoes(model_id),
    quantidade INTEGER NOT NULL,
    preco_praticado DECIMAL(10,2) NOT NULL
);

CREATE TABLE fato_repasse_escrow (
    order_sn VARCHAR(50) PRIMARY KEY REFERENCES fato_pedidos_venda(order_sn),
    comissao_shopee DECIMAL(10,2),
    taxa_servico DECIMAL(10,2),
    taxa_transacao DECIMAL(10,2),
    lucro_liquido_absoluto DECIMAL(10,2) NOT NULL
);

CREATE TABLE fato_trafego_diario (
    id_registro SERIAL PRIMARY KEY,
    item_id BIGINT REFERENCES dim_produtos(item_id),
    data DATE NOT NULL,
    visitantes_unicos INTEGER DEFAULT 0,
    taxa_rejeicao DECIMAL(5,2) DEFAULT 0.00,
    adicoes_carrinho INTEGER DEFAULT 0
);

-- Módulo 4: Ads e Cérebro da IA
CREATE TABLE fato_ads_palavras_chave (
    id_registro SERIAL PRIMARY KEY,
    item_id BIGINT REFERENCES dim_produtos(item_id),
    keyword VARCHAR(100) NOT NULL,
    data DATE NOT NULL,
    impressoes INTEGER,
    cliques INTEGER,
    custo_total DECIMAL(10,2),
    gmv_gerado DECIMAL(10,2)
);

CREATE TABLE ia_analises_estrategicas (
    id_analise SERIAL PRIMARY KEY,
    item_id BIGINT REFERENCES dim_produtos(item_id),
    data_analise TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status_saude VARCHAR(50),
    diagnostico_ia TEXT,
    acoes_recomendadas JSONB
);

-- ==============================================================================
-- MÓDULO 5: CONTROLE DE SINCRONIZAÇÃO (ON-DEMAND) E MEMÓRIA DE DELTA
-- ==============================================================================
CREATE TABLE sys_controle_sync (
    id_sync SERIAL PRIMARY KEY,
    modulo VARCHAR(50) NOT NULL, -- Ex: 'PEDIDOS', 'TRAFEGO_ADS'
    data_inicio_coleta TIMESTAMP, -- De qual data o script começou a buscar
    data_fim_coleta TIMESTAMP,    -- Até que data o script buscou
    data_execucao TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- O momento do clique no botão
    status VARCHAR(20), -- 'SUCESSO', 'ERRO'
    registros_afetados INTEGER
);

-- SEMENTE INICIAL: Diz ao banco que a última "sincronização fantasma" 
-- ocorreu no momento em que a loja nasceu (26/01/2026).
-- Assim, o seu primeiro clique no botão vai puxar do dia 26/01 em diante.
INSERT INTO sys_controle_sync (modulo, data_inicio_coleta, data_fim_coleta, status, registros_afetados)
VALUES 
('PEDIDOS', '2026-01-26 00:00:00', '2026-01-26 00:00:00', 'SUCESSO', 0),
('TRAFEGO_ADS', '2026-01-26 00:00:00', '2026-01-26 00:00:00', 'SUCESSO', 0);

CREATE TABLE log_acoes_shopee (
    id_log SERIAL PRIMARY KEY,
    item_id BIGINT REFERENCES dim_produtos(item_id),
    tipo_acao VARCHAR(50), -- Ex: 'ALTERAR_PRECO', 'PAUSAR_ADS'
    detalhe_acao TEXT,     -- Ex: 'Aumentou de R$ 50 para R$ 56'
    impacto_projetado JSONB, -- Guarda a simulação que você aprovou
    data_aplicacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status_api VARCHAR(20) -- 'SUCESSO', 'ERRO_API'
);