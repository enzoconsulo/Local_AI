-- =============================================================================
-- MIGRAÇÃO 15: FOTO DO PRODUTO NA DIMENSÃO
-- A capa do anúncio (image_url_list[0] do get_item_base_info) passa a ser
-- guardada na dim_produtos. A mesma foto vale para todas as variações do item
-- — decisão de UX: identificar o produto de relance nas tabelas de lucro,
-- plano de ação e boost, sem precisar abrir a Shopee.
-- =============================================================================
BEGIN;

ALTER TABLE dim_produtos ADD COLUMN IF NOT EXISTS imagem_url TEXT;

COMMIT;

-- =============================================================================
-- VALIDAÇÃO PÓS-MIGRAÇÃO
-- =============================================================================
SELECT
    'Migração 15 aplicada com sucesso!' AS status,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'dim_produtos' AND column_name = 'imagem_url'
    ) AS coluna_imagem_criada;
