-- =============================================================================
-- MIGRATION 18: DETALHAMENTO DO REPASSE (ESCROW) DA SHOPEE
-- Descrição:
--   Antes, fato_repasse_escrow guardava só comissão, taxa de serviço, uma
--   "taxa de transação" que nunca vinha preenchida (a chave lida não existe na
--   API) e o repasse final. Tudo o mais que a Shopee desconta sumia num buraco:
--   no porta cartas triplo, R$ 3,68 por pedido sem explicação.
--
--   Conferido ao vivo em get_escrow_detail (14/09/2026), o repasse é:
--     preco_produtos + frete_liquido_vendedor
--       − comissao_shopee − taxa_servico − taxa_transacao − comissao_afiliado
--       − cupom_vendedor − recarga_ads − seguro_frete − reembolso_devolucao
--       − custo_frete_reverso + ajuste_pos_venda − outros_ajustes
--     = lucro_liquido_absoluto (o valor que cai na conta)
--
--   ajuste_pos_venda: a Shopee mexe no repasse DEPOIS de pagar (devolução
--   tardia tira dinheiro, cobertura de devolução põe de volta). Ex. real: um
--   pedido pago com R$ 12,03 terminou em −R$ 2,29 (ajuste de −R$ 14,32).
--
--   Descontos são gravados POSITIVOS. outros_ajustes fecha a conta centavo a
--   centavo (campanhas, moedas, taxas raras), então o detalhamento sempre soma
--   exatamente o repasse. escrow_bruto guarda o order_income inteiro para
--   auditoria.
--
--   Correção de rótulo: custo_frete_reverso recebia o REEMBOLSO do produto
--   (seller_return_refund, ex.: −31,90). Agora o reembolso vai para
--   reembolso_devolucao e custo_frete_reverso fica só com frete de devolução.
--   Linhas antigas são corrigidas quando o sync busca o repasse de novo
--   (detalhado_em IS NULL = ainda no formato antigo).
-- SEGURO PARA RODAR MÚLTIPLAS VEZES.
-- =============================================================================

BEGIN;

ALTER TABLE fato_repasse_escrow
    ADD COLUMN IF NOT EXISTS preco_produtos DECIMAL(10,2),
    ADD COLUMN IF NOT EXISTS comissao_afiliado DECIMAL(10,2),
    ADD COLUMN IF NOT EXISTS cupom_vendedor DECIMAL(10,2),
    ADD COLUMN IF NOT EXISTS recarga_ads DECIMAL(10,2),
    ADD COLUMN IF NOT EXISTS seguro_frete DECIMAL(10,2),
    ADD COLUMN IF NOT EXISTS frete_liquido_vendedor DECIMAL(10,2),
    ADD COLUMN IF NOT EXISTS reembolso_devolucao DECIMAL(10,2),
    ADD COLUMN IF NOT EXISTS outros_ajustes DECIMAL(10,2),
    ADD COLUMN IF NOT EXISTS ajuste_pos_venda DECIMAL(10,2),
    ADD COLUMN IF NOT EXISTS escrow_bruto JSONB,
    ADD COLUMN IF NOT EXISTS detalhado_em TIMESTAMP;

COMMENT ON TABLE fato_repasse_escrow IS
    'Repasse REAL da Shopee por PEDIDO inteiro (get_escrow_detail). Pedido com vários itens: ratear por valor do item (use vw_financeiro_item_pedido).';
COMMENT ON COLUMN fato_repasse_escrow.lucro_liquido_absoluto IS
    'Repasse: valor que a Shopee paga ao vendedor (escrow). NÃO é lucro: ainda falta o custo de fabricação e os anúncios.';
COMMENT ON COLUMN fato_repasse_escrow.preco_produtos IS 'Valor dos produtos no pedido (order_selling_price), antes dos descontos abaixo.';
COMMENT ON COLUMN fato_repasse_escrow.comissao_shopee IS 'Comissão da Shopee (commission_fee).';
COMMENT ON COLUMN fato_repasse_escrow.taxa_servico IS 'Taxa de serviço (service_fee): parte variável + parte fixa por item.';
COMMENT ON COLUMN fato_repasse_escrow.taxa_transacao IS 'Taxa de transação cobrada do VENDEDOR (seller_transaction_fee + parte da taxa de cartão não paga pelo comprador).';
COMMENT ON COLUMN fato_repasse_escrow.ajuste_pos_venda IS 'Ajuste feito pela Shopee depois do pagamento (total_adjustment_amount): negativo = tirou dinheiro (ex.: devolução tardia), positivo = devolveu.';
COMMENT ON COLUMN fato_repasse_escrow.comissao_afiliado IS 'Comissão paga a afiliado da Shopee (order_ams_commission_fee).';
COMMENT ON COLUMN fato_repasse_escrow.cupom_vendedor IS 'Cupom da loja pago pelo vendedor (voucher_from_seller).';
COMMENT ON COLUMN fato_repasse_escrow.recarga_ads IS 'Descontado do repasse para anúncios (ads_escrow_top_up_fee_or_technical_support_fee).';
COMMENT ON COLUMN fato_repasse_escrow.seguro_frete IS 'Seguro/proteção de frete do vendedor (shipping_seller_protection_fee_amount + premium).';
COMMENT ON COLUMN fato_repasse_escrow.frete_liquido_vendedor IS 'Efeito líquido do frete no repasse (buyer_paid_shipping_fee + final_shipping_fee); negativo = o vendedor pagou frete.';
COMMENT ON COLUMN fato_repasse_escrow.reembolso_devolucao IS 'Valor devolvido ao comprador em devolução/reembolso (seller_return_refund, positivo).';
COMMENT ON COLUMN fato_repasse_escrow.custo_frete_reverso IS 'Frete de devolução pago pelo vendedor (reverse_shipping_fee + final_return_to_seller_shipping_fee).';
COMMENT ON COLUMN fato_repasse_escrow.outros_ajustes IS 'Diferença que fecha a conta (campanhas, moedas, taxas raras): preço + frete − descontos − repasse.';
COMMENT ON COLUMN fato_repasse_escrow.escrow_bruto IS 'order_income completo devolvido pela API, para auditoria.';
COMMENT ON COLUMN fato_repasse_escrow.detalhado_em IS 'Quando o detalhamento foi gravado. NULL = linha no formato antigo (sem detalhe).';

COMMIT;

-- =============================================================================
-- VALIDAÇÃO PÓS-MIGRAÇÃO
-- =============================================================================
SELECT
    'Migração 18 aplicada com sucesso!' AS status,
    EXISTS (SELECT 1 FROM information_schema.columns
            WHERE table_name = 'fato_repasse_escrow' AND column_name = 'detalhado_em') AS detalhe_repasse_ok,
    (SELECT COUNT(*) FROM fato_repasse_escrow WHERE detalhado_em IS NULL) AS repasses_a_detalhar;
