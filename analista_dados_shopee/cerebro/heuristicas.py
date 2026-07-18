"""
cerebro/heuristicas.py
======================
Camada determinística pura: nenhuma função aqui toca banco, rede ou Streamlit.
É a âncora anti-alucinação do sistema — a IA externa recebe estas previsões e
só pode se afastar delas justificando com um dado explícito.
"""


# ══════════════════════════════════════════════════════════════════════════════
# PRIORIZAÇÃO
# ══════════════════════════════════════════════════════════════════════════════

def calcular_score_urgencia(d: dict) -> int:
    """Pontua a urgência de um produto de 0 a 100."""
    score = 0

    if d.get("ADS_gasto_7d", 0) > 5 and d.get("ADS_roas_atual", 0) < 1:
        score += 40

    if d.get("LOGISTICA_dias_estoque_restante", 999) < 7:
        score += 35

    if d.get("lucro_liquido_real_7d", 0) < 0:
        score += 30

    if d.get("tendencia_vendas_WoW_perc", 0) < -30:
        score += 25

    if d.get("taxa_abandono_carrinho_perc", 0) > 70 and d.get("REPUTACAO_curtidas_favoritos", 0) > 50:
        score += 20

    if d.get("preco_tendencia_7d_perc", 0) < -15 and d.get("vendas_7d_reais", 0) <= 2:
        score += 10

    if d.get("vendas_7d_reais", 0) == 0 and d.get("ADS_gasto_7d", 0) > 0:
        score += 30

    if d.get("taxa_cancelamento_7d_perc", 0) > 12:
        score += 15

    if d.get("METRICAS_importadas_cancelamentos_7d", 0) > 0 and d.get("vendas_7d_reais", 0) <= 1:
        score += 10

    if d.get("LOJA_macro_conversao_7d", 0) > 0 and d.get("LOJA_macro_conversao_7d", 0) < 2 and d.get("ADS_gasto_7d", 0) > 5:
        score += 10

    # Ruptura do PRÓPRIO anúncio: com venda ativa e estoque publicado curto, o
    # anúncio some da busca antes de o material acabar.
    if d.get("vendas_7d_reais", 0) > 0 and (d.get("LOGISTICA_dias_estoque_shopee") or 999) < 7:
        score += 20

    # ACOS acima do ponto de equilíbrio (margem unitária em % do preço): cada
    # venda atribuída ao ads sai no prejuízo mesmo com ROAS aparentemente ok.
    margem_perc = float(d.get("FINANCEIRO_margem_unitaria_perc") or 0)
    acos = float(d.get("ADS_acos_medio") or 0)
    if d.get("ADS_gasto_7d", 0) > 5 and acos > margem_perc > 0:
        score += 15

    # Preparo estourando o prazo: alimenta o late-shipment da conta (afeta o
    # alcance orgânico da LOJA inteira, não só deste SKU).
    preparo_atrasado = d.get("POSVENDA_preparo_atrasado_perc")
    if (
        int(d.get("POSVENDA_pedidos_preparo_medidos_90d") or 0) >= 3
        and preparo_atrasado is not None and float(preparo_atrasado) >= 20
    ):
        score += 15

    if int(d.get("POSVENDA_devolucoes_90d") or 0) >= 2:
        score += 10

    return min(score, 100)


def calcular_dias_estoque(d: dict) -> int:
    return d.get("LOGISTICA_dias_estoque_restante", 999)


# ══════════════════════════════════════════════════════════════════════════════
# ELASTICIDADE E PREVISÃO DETERMINÍSTICA
# ══════════════════════════════════════════════════════════════════════════════

def calcular_elasticidade_preco_volume(preco_hoje: float, preco_7d: float, vendas_7d: int, vendas_antes: int) -> float:
    if preco_7d <= 0 or vendas_antes <= 0:
        return 0.0
    delta_preco_pct = ((preco_hoje - preco_7d) / preco_7d) * 100
    delta_vendas_pct = ((vendas_7d - vendas_antes) / vendas_antes) * 100
    if abs(delta_preco_pct) < 0.5:
        return 0.0
    return round(delta_vendas_pct / delta_preco_pct, 3)


def calcular_previsao_demanda_7d(d: dict) -> int:
    vendas_7d = max(0, int(d.get("vendas_7d_reais", 0)))
    vendas_30d = max(0, int(d.get("vendas_30d_macro", 0)))
    tendencia = float(d.get("tendencia_vendas_WoW_perc", 0))
    conversao = float(d.get("TRAFEGO_taxa_conversao_perc", 0))
    roas = float(d.get("ADS_roas_atual", 0))
    dias_estoque = int(d.get("LOGISTICA_dias_estoque_restante", 999))
    capacidade = int(d.get("LOGISTICA_capacidade_material_restante", 999_999))
    estoque = int(d.get("estoque_shopee_hoje", 0))

    # O sinal semanal reage rápido, mas é volátil. Com histórico de 30 dias,
    # ancoramos parte da estimativa na média semanal para reduzir ruído.
    forecast_semana = vendas_7d * (1 + tendencia / 100)
    media_semanal_30d = vendas_30d / 4.2857
    forecast = (0.65 * forecast_semana + 0.35 * media_semanal_30d) if vendas_30d > 0 else forecast_semana
    if conversao >= 3.0:
        forecast *= 1.10
    elif conversao <= 1.0:
        forecast *= 0.85
    if roas >= 3.0:
        forecast *= 1.05
    elif roas <= 1.0:
        forecast *= 0.90
    if dias_estoque < 14:
        forecast *= 0.85
    if estoque <= 0:
        forecast *= 0.60
    if capacidade > 0 and capacidade < 999_999:
        forecast = min(forecast, capacidade)
    return int(max(0, round(forecast)))


def calcular_previsao_demanda_30d(d: dict) -> int:
    """Cenário mensal conservador, ancorado no realizado de 30 dias e limitado pela capacidade."""
    vendas_30d = max(0, int(d.get("vendas_30d_reais", d.get("vendas_30d_macro", 0)) or 0))
    vendas_7d = max(0, int(d.get("vendas_7d_reais", 0) or 0))
    capacidade = int(d.get("LOGISTICA_capacidade_material_restante", 999_999) or 999_999)
    conversao_7d = float(d.get("TRAFEGO_taxa_conversao_perc", 0) or 0)
    conversao_30d = float(d.get("TRAFEGO_taxa_conversao_30d_perc", 0) or 0)

    # Se não há histórico mensal, a extrapolação é deliberadamente simples e deve
    # aparecer como baixa evidência na interface, não como previsão de alta certeza.
    base = vendas_30d if vendas_30d > 0 else vendas_7d * (30 / 7)
    ritmo_recente = ((vendas_7d / 7) / (vendas_30d / 30) - 1) if vendas_30d > 0 else 0
    ajuste_ritmo = max(-0.25, min(0.25, ritmo_recente * 0.35))
    ajuste_conversao = 0.0
    if conversao_30d > 0:
        ajuste_conversao = max(-0.10, min(0.10, ((conversao_7d / conversao_30d) - 1) * 0.20))

    forecast = base * (1 + ajuste_ritmo + ajuste_conversao)
    if capacidade > 0 and capacidade < 999_999:
        forecast = min(forecast, capacidade)
    return int(max(0, round(forecast)))


# ══════════════════════════════════════════════════════════════════════════════
# RECOMENDAÇÃO E CLASSIFICAÇÃO
# ══════════════════════════════════════════════════════════════════════════════

def gerar_recomendacao_executiva(d: dict) -> str:
    # ROAS = 0 não significa ROAS ruim se o gasto em ADS também for 0.
    if d.get("ADS_gasto_7d", 0) > 0 and d.get("ADS_roas_atual", 0) < 1:
        return "Pausar ads imediatamente. Revisar palavras-chave e remover 'Seleção Automática'."
    margem_perc = float(d.get("FINANCEIRO_margem_unitaria_perc") or 0)
    acos = float(d.get("ADS_acos_medio") or 0)
    if d.get("ADS_gasto_7d", 0) > 0 and acos > margem_perc > 0:
        return (
            f"ACOS de {acos:.0f}% acima do equilíbrio de {margem_perc:.0f}%: "
            "a campanha consome a margem. Reduzir lance ou pausar manualmente."
        )
    if d.get("taxa_cancelamento_7d_perc", 0) > 10:
        return "Reduzir fricção de compra e revisar embalagem/comunicação para conter cancelamentos."
    if d.get("LOGISTICA_dias_estoque_restante", 999) < 7:
        return "Priorizar reabastecimento de filamento ou elevar preço para proteger a margem."
    if d.get("vendas_7d_reais", 0) > 0 and (d.get("LOGISTICA_dias_estoque_shopee") or 999) < 7:
        return "Repor o estoque publicado do anúncio antes da ruptura: anúncio zerado sai da busca e perde ranking."
    preparo_atrasado = d.get("POSVENDA_preparo_atrasado_perc")
    if (
        int(d.get("POSVENDA_pedidos_preparo_medidos_90d") or 0) >= 3
        and preparo_atrasado is not None and float(preparo_atrasado) >= 20
    ):
        return (
            f"{float(preparo_atrasado):.0f}% dos envios saíram após o prazo: priorizar fila de "
            "impressão/postagem deste produto — o atraso pune o alcance da loja inteira."
        )
    if d.get("PROMO_ativa_tipo"):
        return (
            f"Promoção vigente ({d['PROMO_ativa_tipo']}): não alterar preço por cima dela; "
            "garantir estoque para o pico e reavaliar após o término."
        )
    if d.get("TRAFEGO_taxa_conversao_perc", 0) < 2 and d.get("ADS_gasto_7d", 0) > 5:
        return "Reestruturar tráfego pago (focar em correspondência exata) e revisar imagens de capa."
    if d.get("preco_tendencia_7d_perc", 0) < -10 and d.get("vendas_7d_reais", 0) <= 2:
        return "Reavaliar percepção de preço e focar na criação de Kits/Combos Promocionais."
    return "Manter estratégia atual e monitorar os próximos 7 dias."


def classificar_cluster(d: dict) -> str:
    # ROAS zero sem investimento não é um sinal de risco: não há campanha para avaliar.
    if d.get("lucro_liquido_real_7d", 0) < 0 or (
        d.get("ADS_gasto_7d", 0) > 0 and d.get("ADS_roas_atual", 0) < 1
    ):
        return "Em risco"
    if d.get("LOGISTICA_dias_estoque_restante", 999) < 14:
        return "Reabastecimento"
    if d.get("TRAFEGO_taxa_conversao_perc", 0) >= 3 and d.get("vendas_7d_reais", 0) > 0:
        return "Alto potencial"
    return "Estável"


def classificar_confianca_evidencia(dados: dict) -> tuple[str, str, str]:
    """Classifica a força da evidência; não confunde sinal curto com previsão validada."""
    vendas_30d = int(dados.get("vendas_30d_macro", 0) or 0)
    visitas_30d = int(dados.get("visitas_30d_macro", 0) or 0)
    vendas_7d = int(dados.get("vendas_7d_reais", 0) or 0)
    cobertura_trafego = int(dados.get("COBERTURA_dias_trafego_30d", 0) or 0)
    cobertura_vendas = int(dados.get("COBERTURA_dias_com_venda_30d", 0) or 0)
    preco_mudou = abs(float(dados.get("preco_tendencia_7d_perc", 0) or 0)) >= 0.5

    if vendas_30d >= 20 and visitas_30d >= 100 and vendas_7d > 0 and cobertura_trafego >= 21 and cobertura_vendas >= 7:
        return "Alta", "Volume e cobertura consistentes no período de 30 dias", "success"
    if vendas_30d >= 5 or visitas_30d >= 30:
        cobertura = f"Cobertura: {cobertura_trafego}/30 dias de tráfego, {cobertura_vendas}/30 dias com vendas"
        detalhe = f"Amostra moderada; valide antes de escalar. {cobertura}"
        if not preco_mudou:
            detalhe += ". Sem variação de preço suficiente para medir elasticidade"
        return "Moderada", detalhe, "warning"
    return "Baixa", "Amostra curta ou pouco tráfego; trate projeções como hipótese", "error"


def intervalo_demanda_exploratorio(dados: dict, previsao: float) -> tuple[int, int]:
    """Faixa transparente: combina a previsão com a média semanal de 30 dias e amplia sob pouca evidência."""
    base_30d = float(dados.get("vendas_30d_macro", 0) or 0) / 4.2857
    referencia = previsao if previsao > 0 else base_30d
    confianca, _, _ = classificar_confianca_evidencia(dados)
    amplitude = {"Alta": 0.20, "Moderada": 0.35, "Baixa": 0.60}[confianca]
    if referencia <= 0:
        return 0, 0
    return max(0, round(referencia * (1 - amplitude))), round(referencia * (1 + amplitude))


# ══════════════════════════════════════════════════════════════════════════════
# ALERTAS DE REGRA DE NEGÓCIO
# ══════════════════════════════════════════════════════════════════════════════

def gerar_alertas_criticos(dossie: list[dict]) -> list[dict]:
    alertas = []
    for d in dossie:
        nome = f"{d['nome_produto']} ({d['nome_variacao']})"

        if d.get("ADS_gasto_7d", 0) > 5 and d.get("ADS_roas_atual", 0) < 1:
            alertas.append({
                "nivel": "🔴 CRÍTICO",
                "produto": nome,
                "mensagem": (
                    f"ROAS de {d['ADS_roas_atual']}× — cada R$ 1 em ads retorna "
                    f"menos de R$ 1. Pausar ou reduzir budget imediatamente."
                ),
            })

        dias = calcular_dias_estoque(d)
        if dias < 7:
            alertas.append({
                "nivel": "🟠 URGENTE",
                "produto": nome,
                "mensagem": (
                    f"Estoque de material suficiente para apenas {dias} dias "
                    f"ao ritmo atual de vendas. Reabastecer ou desacelerar vendas."
                ),
            })

        if d.get("lucro_liquido_real_7d", 0) < 0 and d.get("vendas_7d_reais", 0) > 0:
            alertas.append({
                "nivel": "🔴 CRÍTICO",
                "produto": nome,
                "mensagem": (
                    f"Lucro operacional de R$ {d['lucro_liquido_real_7d']:.2f} "
                    f"nos últimos 7 dias. Cada venda piora a situação."
                ),
            })

        margem_perc = float(d.get("FINANCEIRO_margem_unitaria_perc") or 0)
        acos = float(d.get("ADS_acos_medio") or 0)
        if d.get("ADS_gasto_7d", 0) > 5 and acos > margem_perc > 0:
            alertas.append({
                "nivel": "🟠 URGENTE",
                "produto": nome,
                "mensagem": (
                    f"ACOS de {acos:.0f}% acima do ponto de equilíbrio ({margem_perc:.0f}% de "
                    f"margem unitária): cada venda atribuída ao ads sai no prejuízo. "
                    f"Reduzir lance ou pausar a campanha."
                ),
            })

        dias_anuncio = int(d.get("LOGISTICA_dias_estoque_shopee") or 999)
        if d.get("vendas_7d_reais", 0) > 0 and dias_anuncio < 7:
            alertas.append({
                "nivel": "🟠 URGENTE",
                "produto": nome,
                "mensagem": (
                    f"Estoque publicado do anúncio cobre ~{dias_anuncio} dia(s) no ritmo atual. "
                    f"Anúncio zerado sai da busca e perde ranking — repor antes da ruptura."
                ),
            })

        preparo_atrasado = d.get("POSVENDA_preparo_atrasado_perc")
        if (
            int(d.get("POSVENDA_pedidos_preparo_medidos_90d") or 0) >= 5
            and preparo_atrasado is not None and float(preparo_atrasado) >= 30
        ):
            alertas.append({
                "nivel": "🟠 URGENTE",
                "produto": nome,
                "mensagem": (
                    f"{float(preparo_atrasado):.0f}% dos envios deste produto saíram após o prazo "
                    f"nos últimos 90 dias — é combustível direto do late shipment que derruba o "
                    f"alcance da loja. Priorizar fila de impressão/postagem."
                ),
            })

    return alertas


# ══════════════════════════════════════════════════════════════════════════════
# ALAVANCAS DE CRESCIMENTO (correlações medidas → ação; custo zero de IA)
# ══════════════════════════════════════════════════════════════════════════════

def sugerir_alavancas_vendas(d: dict) -> list[dict]:
    """Converte as correlações do dossiê em alavancas acionáveis de venda.

    Nenhuma alavanca é palpite de modelo: cada uma nasce de um número medido
    (cesta de co-compra, dia da semana, ACOS vs. margem, estoque do anúncio,
    share da variação, concentração por UF). nivel='produto' vale para o
    anúncio inteiro (a interface deduplica por item); nivel='variacao' é do SKU.
    """
    alavancas: list[dict] = []
    vendas_7d = int(d.get("vendas_7d_reais", 0) or 0)
    vendas_30d = int(d.get("vendas_30d_reais", d.get("vendas_30d_macro", 0)) or 0)
    visitas_7d = int(d.get("TRAFEGO_visitas_7d", 0) or 0)
    conversao = float(d.get("TRAFEGO_taxa_conversao_perc", 0) or 0)
    gasto_ads = float(d.get("ADS_gasto_7d", 0) or 0)
    acos = float(d.get("ADS_acos_medio", 0) or 0)
    margem_perc = float(d.get("FINANCEIRO_margem_unitaria_perc", 0) or 0)

    if conversao >= 2.5 and visitas_7d <= 30 and vendas_7d >= 1:
        alavancas.append({
            "nivel": "produto", "icone": "🚀", "titulo": "Candidato ao boost gratuito",
            "detalhe": (
                f"Converte {conversao:.1f}% com apenas {visitas_7d} visitas em 7 dias — falta "
                "tráfego, não atratividade. Use o boost gratuito (5 itens a cada 4h) na Visão Central."
            ),
        })

    parceiro = d.get("CESTA_parceiro_top")
    conjuntos = int(d.get("CESTA_pedidos_conjuntos_180d", 0) or 0)
    if parceiro and conjuntos >= 2:
        alavancas.append({
            "nivel": "produto", "icone": "🧺", "titulo": f'Combo com "{parceiro}"',
            "detalhe": (
                f"Comprados juntos em {conjuntos} pedido(s) nos últimos 180 dias. Um combo "
                "(leve mais, pague menos) com desconto pequeno tende a elevar o tíquete médio."
            ),
        })

    melhor_dia = d.get("VENDAS_melhor_dia_semana")
    share_dia = float(d.get("VENDAS_share_melhor_dia_perc", 0) or 0)
    if melhor_dia and share_dia >= 30 and vendas_30d >= 5:
        alavancas.append({
            "nivel": "produto", "icone": "📅", "titulo": f"Concentrar ofertas na {melhor_dia}",
            "detalhe": (
                f"{share_dia:.0f}% das unidades de 90 dias saem na {melhor_dia}. Programe "
                "promoções, voucher e boost para a véspera e o próprio dia."
            ),
        })

    if gasto_ads > 0 and 0 < acos <= max(0.0, margem_perc - 5):
        alavancas.append({
            "nivel": "variacao", "icone": "📈", "titulo": "Espaço para escalar ads",
            "detalhe": (
                f"ACOS de {acos:.0f}% bem abaixo do equilíbrio ({margem_perc:.0f}%): dá para subir "
                "o orçamento mantendo lucro por venda. Ajuste manual no Seller Center."
            ),
        })
    elif gasto_ads > 0 and acos > margem_perc > 0:
        alavancas.append({
            "nivel": "variacao", "icone": "🩸", "titulo": "Ads acima do ponto de equilíbrio",
            "detalhe": (
                f"ACOS de {acos:.0f}% contra margem unitária de {margem_perc:.0f}%: cada venda "
                "atribuída ao ads sai no prejuízo. Reduza o lance ou pause a campanha."
            ),
        })

    dias_anuncio = int(d.get("LOGISTICA_dias_estoque_shopee", 999) or 999)
    if vendas_7d > 0 and dias_anuncio < 7:
        alavancas.append({
            "nivel": "variacao", "icone": "📦", "titulo": "Repor estoque do anúncio",
            "detalhe": (
                f"O estoque publicado cobre ~{dias_anuncio} dia(s) no ritmo atual. Anúncio "
                "zerado some da busca e perde o ranking conquistado."
            ),
        })

    share_var = d.get("PORTFOLIO_share_variacao_30d_perc")
    qtd_vars = int(d.get("qtd_variacoes_produto", 1) or 1)
    vendas_item_30d = int(d.get("PORTFOLIO_vendas_30d_item", 0) or 0)
    if share_var is not None and qtd_vars >= 3 and vendas_item_30d >= 10 and float(share_var) < 10:
        alavancas.append({
            "nivel": "variacao", "icone": "🪓", "titulo": "Variação de cauda",
            "detalhe": (
                f"Apenas {float(share_var):.0f}% das vendas do anúncio em 30 dias. Avalie fundir ou "
                "aposentar esta variação para simplificar a grade e focar foto/preço nas campeãs."
            ),
        })

    uf = d.get("GEO_uf_top")
    uf_share = float(d.get("GEO_uf_top_share_perc", 0) or 0)
    base_uf = int(d.get("GEO_pedidos_com_uf_90d", 0) or 0)
    if uf and base_uf >= 5 and uf_share >= 50:
        alavancas.append({
            "nivel": "produto", "icone": "🗺️", "titulo": f"Demanda concentrada em {uf}",
            "detalhe": (
                f"{uf_share:.0f}% dos pedidos com UF conhecida (90 dias) vêm de {uf}. Priorize "
                "programas de frete que favoreçam a região e cite o prazo real no anúncio."
            ),
        })

    preparo_atrasado = d.get("POSVENDA_preparo_atrasado_perc")
    preparo_medidos = int(d.get("POSVENDA_pedidos_preparo_medidos_90d", 0) or 0)
    if preparo_medidos >= 3 and preparo_atrasado is not None and float(preparo_atrasado) >= 20:
        mediana = d.get("POSVENDA_preparo_mediano_horas")
        sufixo_mediana = f" (mediana {float(mediana):.0f}h)" if mediana is not None else ""
        alavancas.append({
            "nivel": "produto", "icone": "🕒", "titulo": "Preparo estourando o prazo",
            "detalhe": (
                f"{float(preparo_atrasado):.0f}% dos envios de 90 dias saíram após o ship-by{sufixo_mediana}. "
                "Priorize a fila de impressão/postagem deste produto — o late shipment derruba o alcance da loja inteira."
            ),
        })

    recompra_perc = d.get("POSVENDA_recompra_perc_180d")
    base_recompra = int(d.get("POSVENDA_pedidos_identificados_180d", 0) or 0)
    if recompra_perc is not None and float(recompra_perc) >= 20 and base_recompra >= 5:
        alavancas.append({
            "nivel": "produto", "icone": "🔁", "titulo": "Clientes que voltam",
            "detalhe": (
                f"{float(recompra_perc):.0f}% dos pedidos de 180 dias vieram de compradores que já "
                "haviam comprado na loja. Voucher de recompra e kits (cesta) rendem mais aqui do que ads frio."
            ),
        })

    devolucoes = int(d.get("POSVENDA_devolucoes_90d", 0) or 0)
    if devolucoes >= 2:
        motivo = d.get("POSVENDA_devolucao_motivo")
        sufixo_motivo = f" Motivo mais recente: {motivo}." if motivo else ""
        alavancas.append({
            "nivel": "produto", "icone": "↩️", "titulo": "Devoluções recorrentes",
            "detalhe": (
                f"{devolucoes} devolução(ões) em 90 dias.{sufixo_motivo} Revise qualidade, "
                "embalagem e descrição antes de investir em mais tráfego."
            ),
        })

    return alavancas
