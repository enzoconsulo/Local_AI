"""
Testes OFFLINE do detalhamento do repasse (workers/sync_pedidos.repasse_do_escrow).

Os valores vêm de get_escrow_detail de pedidos reais consultados em 14/09/2026
(só os campos numéricos). A regra testada: preço + frete − descontos +
ajuste_pos_venda − outros_ajustes = repasse, sempre, centavo por centavo.

Rodar:  python tests/test_repasse_escrow.py  (pytest também funciona)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workers.sync_pedidos import COLUNAS_REPASSE, repasse_do_escrow  # noqa: E402

DESCONTOS = (
    "comissao_shopee", "taxa_servico", "taxa_transacao", "comissao_afiliado", "cupom_vendedor",
    "recarga_ads", "seguro_frete", "reembolso_devolucao", "custo_frete_reverso", "outros_ajustes",
)


def _fecha_a_conta(r: dict) -> bool:
    calculado = (
        r["preco_produtos"] + r["frete_liquido_vendedor"]
        - sum(r[c] for c in DESCONTOS) + r["ajuste_pos_venda"]
    )
    return round(calculado, 2) == r["lucro_liquido_absoluto"]


def test_pedido_normal_separa_recarga_de_ads_e_seguro_de_frete():
    # Porta cartas triplo a R$ 31,90: os "R$ 3,68 sem explicação" eram estes dois campos.
    r = repasse_do_escrow("260907C9WFR838", {
        "items": [{"selling_price": 31.9, "quantity_purchased": 1}],
        "order_selling_price": 31.9, "order_original_price": 31.9,
        "commission_fee": 5.74, "service_fee": 4.64,
        "seller_transaction_fee": 0, "credit_card_transaction_fee": 0,
        "ads_escrow_top_up_fee_or_technical_support_fee": 3.19,
        "shipping_seller_protection_fee_amount": 0.49,
        "buyer_paid_shipping_fee": 0, "final_shipping_fee": 0,
        "escrow_amount": 17.84, "escrow_amount_after_adjustment": 17.84,
    })
    assert r["recarga_ads"] == 3.19
    assert r["seguro_frete"] == 0.49
    assert r["outros_ajustes"] == 0
    assert r["lucro_liquido_absoluto"] == 17.84
    assert _fecha_a_conta(r)


def test_pedido_com_afiliado_cupom_da_loja_e_frete_pago_pelo_comprador():
    r = repasse_do_escrow("260722AAV4J14J", {
        "items": [{"selling_price": 31.9}],
        "commission_fee": 5.2, "service_fee": 4.98,
        "order_ams_commission_fee": 2.86, "voucher_from_seller": 3,
        "ads_escrow_top_up_fee_or_technical_support_fee": 2.89,
        "buyer_paid_shipping_fee": 1.44, "final_shipping_fee": -1.44,
        "coins": 0.26, "escrow_amount": 12.97, "escrow_amount_after_adjustment": 12.97,
    })
    assert r["comissao_afiliado"] == 2.86
    assert r["cupom_vendedor"] == 3
    assert r["frete_liquido_vendedor"] == 0
    assert r["outros_ajustes"] == 0  # moedas Shopee não saem do vendedor
    assert _fecha_a_conta(r)


def test_reembolso_vai_para_reembolso_devolucao_e_nao_para_frete_reverso():
    # Antes da migração 18, os −31,90 caíam em custo_frete_reverso.
    r = repasse_do_escrow("2608102576R774", {
        "items": [{"selling_price": 31.9}],
        "order_original_price": 31.9, "order_seller_discount": 31.9,
        "commission_fee": 0, "service_fee": 0,
        "seller_return_refund": -31.9, "drc_adjustable_refund": 30.32,
        "shipping_seller_protection_fee_amount": 0.49,
        "reverse_shipping_fee": 0, "final_shipping_fee": 0,
        "escrow_amount": -0.49, "escrow_amount_after_adjustment": -0.49,
    })
    assert r["preco_produtos"] == 31.9
    assert r["reembolso_devolucao"] == 31.9
    assert r["custo_frete_reverso"] == 0
    assert r["lucro_liquido_absoluto"] == -0.49
    assert _fecha_a_conta(r)


def test_devolucao_parcial_usa_preco_dos_itens_e_nao_desconta_reembolso_duas_vezes():
    # 2 unidades, 1 devolvida: order_selling_price já vem com 20,40 abatidos.
    r = repasse_do_escrow("260409C35CM8HS", {
        "items": [{"selling_price": 40.8, "quantity_purchased": 2}],
        "order_selling_price": 20.4, "order_original_price": 40.8, "order_seller_discount": 20.4,
        "commission_fee": 3.67, "service_fee": 4.41,
        "credit_card_transaction_fee": 3.89, "buyer_transaction_fee": 3.89,
        "seller_return_refund": -20.4, "coins": 5.07,
        "buyer_paid_shipping_fee": 7.51, "final_shipping_fee": -7.51,
        "escrow_amount": 12.32, "escrow_amount_after_adjustment": 12.32,
    })
    assert r["preco_produtos"] == 40.8
    assert r["reembolso_devolucao"] == 20.4
    assert r["taxa_transacao"] == 0  # juros do parcelamento pagos pelo comprador
    assert r["outros_ajustes"] == 0
    assert _fecha_a_conta(r)


def test_ajuste_pos_venda_explica_repasse_que_virou_negativo():
    # Pago com R$ 12,03 e depois a Shopee tirou R$ 14,32 (devolução tardia).
    r = repasse_do_escrow("260618EBGX8PDT", {
        "items": [{"selling_price": 22.9}],
        "commission_fee": 4.12, "service_fee": 4.46,
        "ads_escrow_top_up_fee_or_technical_support_fee": 2.29,
        "escrow_amount": 12.03, "escrow_amount_after_adjustment": -2.29,
        "total_adjustment_amount": -14.32,
    })
    assert r["ajuste_pos_venda"] == -14.32
    assert r["lucro_liquido_absoluto"] == -2.29
    assert r["outros_ajustes"] == 0
    assert _fecha_a_conta(r)


def test_taxa_de_cartao_so_conta_quando_nao_foi_paga_pelo_comprador():
    pago_pelo_comprador = repasse_do_escrow("26071818Q1NBMM", {
        "items": [{"selling_price": 36.9}], "commission_fee": 6.64, "service_fee": 4.74,
        "ads_escrow_top_up_fee_or_technical_support_fee": 3.69,
        "buyer_paid_shipping_fee": 5.42, "final_shipping_fee": -5.42,
        "credit_card_transaction_fee": 4.15, "buyer_transaction_fee": 4.15,
        "escrow_amount": 21.83, "escrow_amount_after_adjustment": 21.83,
    })
    assert pago_pelo_comprador["taxa_transacao"] == 0
    assert pago_pelo_comprador["outros_ajustes"] == 0

    pago_pelo_vendedor = repasse_do_escrow("X", {
        "items": [{"selling_price": 50}], "credit_card_transaction_fee": 2.5, "escrow_amount": 47.5,
    })
    assert pago_pelo_vendedor["taxa_transacao"] == 2.5
    assert _fecha_a_conta(pago_pelo_vendedor)


def test_desconto_desconhecido_aparece_em_outros_ajustes():
    # Um campo novo que a Shopee inventar não some: a diferença fica visível.
    r = repasse_do_escrow("X", {"order_selling_price": 50, "commission_fee": 7, "escrow_amount": 40})
    assert r["outros_ajustes"] == 3
    assert _fecha_a_conta(r)


def test_resposta_incompleta_nao_quebra_e_gera_todas_as_colunas():
    r = repasse_do_escrow("VAZIO", {"escrow_amount": None, "commission_fee": "abc"})
    assert set(COLUNAS_REPASSE) <= set(r)
    assert r["lucro_liquido_absoluto"] == 0 and r["comissao_shopee"] == 0
    assert json.loads(r["escrow_bruto"]) == {"escrow_amount": None, "commission_fee": "abc"}


def test_usa_escrow_ajustado_quando_existe():
    r = repasse_do_escrow("AJ", {"order_selling_price": 20, "escrow_amount": 15, "escrow_amount_after_adjustment": 14})
    assert r["lucro_liquido_absoluto"] == 14
    assert r["outros_ajustes"] == 6


if __name__ == "__main__":
    testes = [(nome, f) for nome, f in globals().items() if nome.startswith("test_") and callable(f)]
    for nome, funcao in testes:
        funcao()
        print(f"  ok  {nome}")
    print(f"{len(testes)} teste(s) passaram.")
