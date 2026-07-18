"""
Testes OFFLINE da camada de correlação profunda do dossiê (v3).

Nenhum teste toca banco, rede ou Streamlit: validam a montagem determinística
(_montar_dados_variacao), a curva ABC, as alavancas de crescimento e a
compactação do payload da IA.

Rodar:  python tests/test_cerebro_correlacoes.py  (padrão do repo; pytest também funciona)
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cerebro.dossie import _montar_dados_variacao, classificar_curva_abc  # noqa: E402
from cerebro.heuristicas import sugerir_alavancas_vendas  # noqa: E402
from cerebro.motor_ia import CAMPOS_PROMPT_7D, compactar_lote_por_horizonte  # noqa: E402


def _linha_base(**overrides) -> dict:
    """Linha sintética com a mesma forma da QUERY_DOSSIE (valores já COALESCEd)."""
    linha = {
        "item_id": 111, "model_id": 222,
        "nome_atual": "Suporte Articulado", "nome_variacao": "Preto",
        "preco_venda_atual": 30.0, "estrelas": 4.8, "curtidas_favoritos": 120,
        "estoque_na_shopee": 10, "tempo_preparo_dias": 3,
        "preco_hoje": 30.0, "preco_7d_atras": 30.0, "preco_30d_atras": 28.0,
        "estoque_hoje": 10, "estoque_7d_atras": 12, "estoque_30d_atras": 20,
        "vendas_7d": 7, "dias_com_venda_7d": 5, "vendas_30d": 15, "dias_com_venda_30d": 12,
        "vendas_semana_passada": 5, "pedidos_7d": 7, "cancelamentos_7d": 0,
        "pedidos_30d": 15, "cancelamentos_30d": 1, "vendas_30d_item_total": 30,
        "receita_liquida_7d": 150.0, "receita_liquida_30d": 500.0, "taxa_shopee_unitaria": 9.0,
        "impressoes_org": 400, "registros_impressoes_org": 7,
        "cliques_org": 40, "registros_cliques_org": 7,
        "rejeicao_media": 25.0, "impressoes_ads": 300, "registros_impressoes_ads": 7,
        "cliques_ads": 30, "registros_cliques_ads": 7, "gmv_ads": 120.0,
        "visitas_7d": 60, "carrinhos_7d": 15, "dias_trafego_7d": 7,
        "gasto_ads_7d": 12.0, "dias_ads_7d": 7,
        "visitas_30d": 200, "carrinhos_30d": 50, "dias_trafego_30d": 28,
        "impressoes_org_30d": 1500, "registros_impressoes_org_30d": 28,
        "cliques_org_30d": 150, "registros_cliques_org_30d": 28,
        "gasto_ads_30d": 40.0, "dias_ads_30d": 28,
        "impressoes_ads_30d": 1200, "registros_impressoes_ads_30d": 28,
        "cliques_ads_30d": 120, "registros_cliques_ads_30d": 28,
        "gmv_ads_30d": 400.0, "conversoes_ads_30d": 10, "itens_vendidos_ads_30d": 12,
        "qtd_variacoes_produto": 2,
        "vendas_importadas_7d": 0, "receita_importada_7d": 0,
        "cancelamentos_importados_7d": 0, "devolucoes_importadas_7d": 0,
        "reembolsos_importados_7d": 0, "estoque_importado_7d": 0, "custo_importado_7d": 0,
        "receita_macro_7d": 0, "conversao_macro_7d": 0, "roas_macro_7d": 0,
        "visitas_macro_7d": 0, "estoque_macro_7d": 0,
        "custo_fabricacao_com_refugo": 3.20, "peso_gramas": 30.0,
        "taxa_perda_percentual": 0, "nome_material": "PLA Preto",
        "estoque_material_atual": 2.0, "unidade_material": "kg",
        "ultima_acao": None, "ultimo_detalhe": None, "ultima_projecao": None,
        # Camada de correlação (nível do item)
        "imagem_url": "https://cf.shopee.com.br/file/abc",
        "melhor_dow": 6, "unidades_melhor_dia": 8, "unidades_dow_90d": 20,
        "uf_top": "SP", "pedidos_uf": 6, "pedidos_uf_total": 10,
        "cesta_parceiro_item_id": 999, "cesta_parceiro_nome": "Organizador de Mesa",
        "cesta_pedidos_conjuntos": 3,
        "api_views_fim": 500.0, "api_views_ini": 300.0, "api_snapshots_views": 2,
        "api_curtidas_fim": 45.0, "api_curtidas_ini": 40.0,
        # Pós-venda via API (migração 17)
        "recompra_pedidos_ident": 10, "recompra_pedidos_recorrentes": 3,
        "recompra_compradores_unicos": 9,
        "preparo_pedidos_medidos": 8, "preparo_mediano_horas": 30.4,
        "pedidos_preparo_atrasado": 2, "entrega_mediana_dias": 6.7,
        "devolucoes_90d": 1, "devolucao_motivo_recente": "PRODUTO_DANIFICADO",
        "promo_ativa_tipo": "DESCONTO", "promo_ativa_fim": datetime(2026, 7, 25, 23, 59),
    }
    linha.update(overrides)
    return linha


def test_derivados_de_correlacao_profunda():
    d = _montar_dados_variacao(_linha_base())

    # Margem unitária: 30,00 − 9,00 (taxa) − 3,20 (fabricação) = 17,80 → 59,3%
    assert d["FINANCEIRO_margem_unitaria_reais"] == 17.80
    assert d["FINANCEIRO_margem_unitaria_perc"] == 59.3

    # Estoque do anúncio: 10 un. ÷ (7 vendas / 7 dias) = 10 dias
    assert d["LOGISTICA_dias_estoque_shopee"] == 10

    # Participação da variação: 15 de 30 vendas do item = 50%
    assert d["PORTFOLIO_share_variacao_30d_perc"] == 50.0
    assert d["PORTFOLIO_vendas_30d_item"] == 30

    # Perfil semanal, geografia, cesta e API
    assert d["VENDAS_melhor_dia_semana"] == "sábado"
    assert d["VENDAS_share_melhor_dia_perc"] == 40.0
    assert d["GEO_uf_top"] == "SP" and d["GEO_uf_top_share_perc"] == 60.0
    assert d["CESTA_parceiro_top"] == "Organizador de Mesa"
    assert d["CESTA_pedidos_conjuntos_180d"] == 3
    assert d["API_views_7d"] == 200 and d["API_curtidas_7d"] == 5
    assert d["imagem_url"].startswith("https://")

    # Pós-venda: recompra 3/10 = 30%; preparo atrasado 2/8 = 25%; promo em ISO
    assert d["POSVENDA_recompra_perc_180d"] == 30.0
    assert d["POSVENDA_preparo_mediano_horas"] == 30.4
    assert d["POSVENDA_preparo_atrasado_perc"] == 25.0
    assert d["POSVENDA_entrega_mediana_dias"] == 6.7
    assert d["POSVENDA_devolucoes_90d"] == 1
    assert d["PROMO_ativa_tipo"] == "DESCONTO"
    assert d["PROMO_ativa_fim"] == "2026-07-25T23:59:00"


def test_pos_venda_sem_dados_fica_none():
    d = _montar_dados_variacao(_linha_base(
        recompra_pedidos_ident=None, recompra_pedidos_recorrentes=None,
        recompra_compradores_unicos=None, preparo_pedidos_medidos=None,
        preparo_mediano_horas=None, pedidos_preparo_atrasado=None,
        entrega_mediana_dias=None, devolucoes_90d=None,
        devolucao_motivo_recente=None, promo_ativa_tipo=None, promo_ativa_fim=None,
    ))
    assert d["POSVENDA_recompra_perc_180d"] is None
    assert d["POSVENDA_preparo_atrasado_perc"] is None
    assert d["POSVENDA_entrega_mediana_dias"] is None
    assert d["POSVENDA_devolucoes_90d"] == 0
    assert d["PROMO_ativa_tipo"] is None and d["PROMO_ativa_fim"] is None


def test_escudo_api_com_um_snapshot():
    d = _montar_dados_variacao(_linha_base(api_snapshots_views=1, api_views_ini=500.0))
    # 1 snapshot: delta NÃO mensurável → None (nunca zero), acumulado preservado
    assert d["API_views_7d"] is None and d["API_curtidas_7d"] is None
    assert d["API_views_acumuladas"] == 500


def test_item_sem_correlacoes_fica_none():
    d = _montar_dados_variacao(_linha_base(
        melhor_dow=None, unidades_melhor_dia=None, unidades_dow_90d=None,
        uf_top=None, pedidos_uf=None, pedidos_uf_total=None,
        cesta_parceiro_item_id=None, cesta_parceiro_nome=None, cesta_pedidos_conjuntos=None,
        api_views_fim=None, api_views_ini=None, api_snapshots_views=0,
        api_curtidas_fim=None, api_curtidas_ini=None, vendas_30d_item_total=0,
    ))
    assert d["VENDAS_melhor_dia_semana"] is None
    assert d["GEO_uf_top"] is None
    assert d["CESTA_parceiro_top"] is None
    assert d["API_views_7d"] is None and d["API_views_acumuladas"] is None
    assert d["PORTFOLIO_share_variacao_30d_perc"] is None


def test_curva_abc_por_lucro():
    dossie = [
        {"lucro_liquido_real_30d": 80, "vendas_30d_reais": 10},
        {"lucro_liquido_real_30d": 15, "vendas_30d_reais": 5},
        {"lucro_liquido_real_30d": 5, "vendas_30d_reais": 2},
        {"lucro_liquido_real_30d": -3, "vendas_30d_reais": 1},
    ]
    classificar_curva_abc(dossie)
    assert [d["PORTFOLIO_curva_abc"] for d in dossie] == ["A", "B", "C", "C"]

    # Líder sozinho acima de 80% continua sendo A (corte pelo acumulado ANTES)
    dossie_lider = [
        {"lucro_liquido_real_30d": 95, "vendas_30d_reais": 20},
        {"lucro_liquido_real_30d": 5, "vendas_30d_reais": 1},
    ]
    classificar_curva_abc(dossie_lider)
    assert dossie_lider[0]["PORTFOLIO_curva_abc"] == "A"

    # Loja sem lucro no mês: cai para unidades vendidas como base
    dossie_sem_lucro = [
        {"lucro_liquido_real_30d": -10, "vendas_30d_reais": 30},
        {"lucro_liquido_real_30d": -2, "vendas_30d_reais": 1},
    ]
    classificar_curva_abc(dossie_sem_lucro)
    assert dossie_sem_lucro[0]["PORTFOLIO_curva_abc"] == "A"


def test_alavancas_de_crescimento():
    base = {
        "vendas_7d_reais": 3, "vendas_30d_reais": 20, "TRAFEGO_visitas_7d": 20,
        "TRAFEGO_taxa_conversao_perc": 5.0, "ADS_gasto_7d": 10.0, "ADS_acos_medio": 70.0,
        "FINANCEIRO_margem_unitaria_perc": 59.3, "LOGISTICA_dias_estoque_shopee": 3,
        "CESTA_parceiro_top": "Organizador de Mesa", "CESTA_pedidos_conjuntos_180d": 3,
        "VENDAS_melhor_dia_semana": "sábado", "VENDAS_share_melhor_dia_perc": 40.0,
        "PORTFOLIO_share_variacao_30d_perc": 5.0, "qtd_variacoes_produto": 4,
        "PORTFOLIO_vendas_30d_item": 40,
        "GEO_uf_top": "SP", "GEO_uf_top_share_perc": 60.0, "GEO_pedidos_com_uf_90d": 10,
        "POSVENDA_preparo_atrasado_perc": 25.0, "POSVENDA_pedidos_preparo_medidos_90d": 8,
        "POSVENDA_preparo_mediano_horas": 30.0,
        "POSVENDA_recompra_perc_180d": 30.0, "POSVENDA_pedidos_identificados_180d": 10,
        "POSVENDA_devolucoes_90d": 2, "POSVENDA_devolucao_motivo": "PRODUTO_DANIFICADO",
    }
    titulos = {a["titulo"] for a in sugerir_alavancas_vendas(base)}
    assert "Candidato ao boost gratuito" in titulos
    assert 'Combo com "Organizador de Mesa"' in titulos
    assert "Concentrar ofertas na sábado" in titulos
    assert "Ads acima do ponto de equilíbrio" in titulos
    assert "Repor estoque do anúncio" in titulos
    assert "Variação de cauda" in titulos
    assert "Demanda concentrada em SP" in titulos
    assert "Preparo estourando o prazo" in titulos
    assert "Clientes que voltam" in titulos
    assert "Devoluções recorrentes" in titulos

    # ACOS com folga vira alavanca de escala (nunca junto com a de sangria)
    saudavel = dict(base, ADS_acos_medio=20.0)
    titulos_saudavel = {a["titulo"] for a in sugerir_alavancas_vendas(saudavel)}
    assert "Espaço para escalar ads" in titulos_saudavel
    assert "Ads acima do ponto de equilíbrio" not in titulos_saudavel

    # SKU sem sinais não inventa alavanca
    assert sugerir_alavancas_vendas({}) == []


def test_payload_7d_compacto_com_sinais():
    lote = [{
        "item_id": 111, "nome_produto": "Suporte Articulado",
        "metricas_macro_produto_30_dias": {"visitas_totais_30d": 200},
        "sinais_produto": {"cesta_parceiro_top": "Organizador de Mesa"},
        "variacoes_ativas": [{
            "model_id": 222, "nome_variacao": "Preto", "preco_atual": 30.0,
            "margem_unitaria_perc": 59.3, "share_variacao_30d_perc": 50.0,
            "dias_estoque_shopee": 10, "curva_abc": "A",
            "campo_que_nao_vai_para_o_modelo": "xyz",
            "memoria_estrategica_30d": None,
        }],
    }]
    compacto = compactar_lote_por_horizonte(lote, "7d")[0]
    variacao = compacto["variacoes_ativas"][0]

    # Sinais decisivos passam; campo fora da lista é cortado; sinais_produto
    # seguem UMA vez por produto (economia de tokens por SKU)
    assert {"margem_unitaria_perc", "share_variacao_30d_perc", "dias_estoque_shopee", "curva_abc"} <= CAMPOS_PROMPT_7D
    assert variacao["margem_unitaria_perc"] == 59.3 and variacao["curva_abc"] == "A"
    assert "campo_que_nao_vai_para_o_modelo" not in variacao
    assert compacto["sinais_produto"]["cesta_parceiro_top"] == "Organizador de Mesa"
    # No horizonte 7d as macros de 30d continuam fora do payload
    assert compacto["metricas_macro_produto_30_dias"] == {}


if __name__ == "__main__":
    test_derivados_de_correlacao_profunda()
    test_escudo_api_com_um_snapshot()
    test_item_sem_correlacoes_fica_none()
    test_pos_venda_sem_dados_fica_none()
    test_curva_abc_por_lucro()
    test_alavancas_de_crescimento()
    test_payload_7d_compacto_com_sinais()
    print("Testes offline da camada de correlação do dossiê OK")
