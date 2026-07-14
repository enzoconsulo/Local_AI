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
    if d.get("taxa_cancelamento_7d_perc", 0) > 10:
        return "Reduzir fricção de compra e revisar embalagem/comunicação para conter cancelamentos."
    if d.get("LOGISTICA_dias_estoque_restante", 999) < 7:
        return "Priorizar reabastecimento de filamento ou elevar preço para proteger a margem."
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

    return alertas
