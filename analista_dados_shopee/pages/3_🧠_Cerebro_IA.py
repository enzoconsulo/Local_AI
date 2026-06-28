"""
pages/3___Cerebro_IA.py
========================
Conselho de Administração IA (CFO, CMO, COO) + Atuador Shopee.

Correções aplicadas nesta versão
---------------------------------
#7  memoria_ia — DISTINCT ON model_id (não mais item_id); salvar_log_acao
    agora grava o model_id, impedindo que ações de uma variação "contaminem"
    a memória de variações-irmãs do mesmo produto.
#8  validar_sugestao_ia() — camada de segurança em código Python que bloqueia
    sugestões fora da curva ANTES de exibir o botão de aprovação, sem depender
    do LLM "obedecer" o prompt.

Melhorias adicionais desta versão
----------------------------------
+   Pool de conexões via utils/db_pool (sem abrir/fechar por requisição).
+   calcular_score_urgencia() — prioriza produtos críticos no lote enviado à IA.
+   calcular_dias_estoque() — calcula autonomia de material ao ritmo atual.
+   gerar_alertas_criticos() — alertas determinísticos (sem LLM) para situações
    extremas: ROAS < 1×, material acabando em < 7 dias, lucro negativo.
+   Dashboard de KPIs agregados antes dos relatórios por produto.
+   Port corrigido para 8000 (alinhado com data_app.py e mesclar_llm.py).
+   tamanho_lote padrão elevado para 8 (menos chamadas RunPod, mais contexto).
+   Importação de criar_combo_shopee movida para o topo (evita ImportError tardio).
"""

import json
import os
import re
import sys
import litellm
import psycopg2.extras
import streamlit as st
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))
load_dotenv(ROOT_DIR / "CHAVES_DADOS.env")

from utils.shopee_core import (
    atualizar_preco_shopee,
    criar_promocao_shopee,
    criar_combo_shopee,
)
from utils.db_pool import get_connection

st.set_page_config(
    page_title="Cérebro Analítico & Atuador",
    page_icon="🧠",
    layout="wide",
)

# Porta 8000 — alinhada com data_app.py e o bootstrap llm.py
LITELLM_BASE = "http://localhost:8000/v1/chat/completions"


# ==============================================================================
# SEÇÃO 1 — EXTRAÇÃO DO DATA WAREHOUSE
# ==============================================================================

def gerar_dossie_produtos_com_memoria():
    """
    Query principal do Cérebro IA.

    Correções aplicadas:
    - Fix #4  vendas_anteriores usa JOIN com fato_repasse_escrow para comparar
              apenas pedidos concluídos (igual a vendas_7d).
    - Fix #7  memoria_ia usa DISTINCT ON (model_id) em vez de (item_id),
              e faz JOIN com v.model_id para não vazar memória entre variações.
    - Extra   Adiciona dias_estoque_restante calculado diretamente no SQL.
    """
    query = """
    WITH vendas_7d AS (
        SELECT
            i.model_id,
            SUM(i.quantidade)                                         AS qtd_vendida,
            SUM(r.lucro_liquido_absoluto)                             AS lucro_liquido_total,
            AVG(r.comissao_shopee + r.taxa_servico + r.taxa_transacao) AS taxa_media_shopee
        FROM fato_itens_pedido i
        JOIN fato_repasse_escrow  r ON i.order_sn  = r.order_sn
        JOIN fato_pedidos_venda   p ON p.order_sn  = r.order_sn
        WHERE p.data_hora_criacao >= CURRENT_DATE - INTERVAL '7 days'
        GROUP BY i.model_id
    ),
    vendas_anteriores AS (
        -- Fix #4: mesmo JOIN com escrow para comparar maçãs com maçãs
        SELECT
            i.model_id,
            SUM(i.quantidade) AS qtd_vendida_antiga
        FROM fato_itens_pedido i
        JOIN fato_repasse_escrow  r ON i.order_sn = r.order_sn
        JOIN fato_pedidos_venda   p ON p.order_sn = r.order_sn
        WHERE p.data_hora_criacao >= CURRENT_DATE - INTERVAL '14 days'
          AND p.data_hora_criacao <  CURRENT_DATE - INTERVAL '7 days'
        GROUP BY i.model_id
    ),
    ads_7d AS (
        SELECT
            item_id,
            SUM(impressoes)  AS impressoes,
            SUM(cliques)     AS cliques,
            SUM(custo_total) AS gasto_ads
        FROM fato_ads_palavras_chave
        WHERE data >= CURRENT_DATE - INTERVAL '7 days'
        GROUP BY item_id
    ),
    trafego_7d AS (
        SELECT
            item_id,
            SUM(visitantes_unicos) AS visitas,
            SUM(adicoes_carrinho)  AS carrinhos
        FROM fato_trafego_diario
        WHERE data >= CURRENT_DATE - INTERVAL '7 days'
        GROUP BY item_id
    ),
    memoria_ia AS (
        -- Fix #7: DISTINCT ON model_id (não item_id) e JOIN correto abaixo
        -- Logs antigos sem model_id (model_id IS NULL) são excluídos — ok,
        -- pois estavam "vazando" para variações-irmãs.
        SELECT DISTINCT ON (model_id)
            item_id, model_id, tipo_acao, detalhe_acao,
            impacto_projetado, data_aplicacao
        FROM log_acoes_shopee
        WHERE status_api = 'SUCESSO' AND model_id IS NOT NULL
        ORDER BY model_id, data_aplicacao DESC
    )
    SELECT
        p.item_id,
        v.model_id,
        p.nome_atual,
        v.nome_variacao,
        v.preco_venda_atual,
        COALESCE(p.nota_media_estrelas, 0)   AS estrelas,
        COALESCE(p.likes_count, 0)           AS curtidas_favoritos,
        COALESCE(v.estoque_shopee, 0)        AS estoque_na_shopee,
        COALESCE(p.dias_pre_encomenda, 3)    AS tempo_preparo_dias,

        COALESCE(ven.qtd_vendida, 0)         AS vendas_7d,
        COALESCE(vant.qtd_vendida_antiga, 0) AS vendas_semana_passada,
        COALESCE(ven.taxa_media_shopee, 0)   AS taxa_shopee_unitaria,
        COALESCE(ven.lucro_liquido_total, 0) AS receita_liquida_7d,
        COALESCE(t.visitas, 0)               AS visitas_7d,
        COALESCE(t.carrinhos, 0)             AS carrinhos_7d,
        COALESCE(a.gasto_ads, 0)             AS gasto_ads_7d,

        -- Custo de fabricação já com refugo embutido
        (
            (
                (CASE WHEN mat.unidade_medida = 'kg'
                      THEN (eng.peso_gramas / 1000.0)
                      ELSE eng.peso_gramas END
                 * mat.custo_por_unidade)
                + (eng.tempo_impressao_minutos * maq.custo_energia_hora / 60.0)
                + COALESCE(eng.custo_embalagem, 0)
            ) * (1 + (COALESCE(eng.taxa_perda_percentual, 0) / 100.0))
        )                                    AS custo_fabricacao_com_refugo,

        eng.peso_gramas,
        eng.taxa_perda_percentual,
        mat.nome                             AS nome_material,
        COALESCE(mat.estoque_atual, 0)       AS estoque_material_atual,
        mat.unidade_medida                   AS unidade_material,

        -- Memória da última ação por VARIAÇÃO (Fix #7)
        m.tipo_acao          AS ultima_acao,
        m.detalhe_acao       AS ultimo_detalhe,
        m.impacto_projetado  AS ultima_projecao

    FROM dim_produtos p
    JOIN dim_variacoes v              ON p.item_id   = v.item_id
    LEFT JOIN map_engenharia_produto eng ON v.model_id = eng.model_id
    LEFT JOIN dim_materiais mat       ON eng.id_material = mat.id_material
    LEFT JOIN dim_maquinas  maq       ON eng.id_maquina  = maq.id_maquina
    LEFT JOIN vendas_7d     ven       ON v.model_id  = ven.model_id
    LEFT JOIN vendas_anteriores vant  ON v.model_id  = vant.model_id
    LEFT JOIN ads_7d        a         ON p.item_id   = a.item_id
    LEFT JOIN trafego_7d    t         ON p.item_id   = t.item_id
    LEFT JOIN memoria_ia    m         ON v.model_id  = m.model_id   -- Fix #7
    WHERE p.status_shopee = 'NORMAL';
    """

    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(query)
            registros = cur.fetchall()

    dossie = []
    for r in registros:
        preco        = float(r["preco_venda_atual"] or 0)
        custo_fab    = float(r["custo_fabricacao_com_refugo"] or 0)
        receita_liq  = float(r["receita_liquida_7d"])
        gasto_ads    = float(r["gasto_ads_7d"])
        vendas       = int(r["vendas_7d"])
        vendas_antes = int(r["vendas_semana_passada"])
        visitas      = int(r["visitas_7d"])
        carrinhos    = int(r["carrinhos_7d"])

        lucro_operacional    = receita_liq - (custo_fab * vendas) - gasto_ads
        roas_atual           = round(receita_liq / gasto_ads, 2) if gasto_ads > 0 else 0
        taxa_conversao       = round(vendas / visitas * 100, 2) if visitas > 0 else 0
        taxa_abandono        = round((carrinhos - vendas) / carrinhos * 100, 2) if carrinhos > 0 else 0
        tendencia_perc       = (
            round((vendas - vendas_antes) / vendas_antes * 100, 2)
            if vendas_antes > 0 else (100 if vendas > 0 else 0)
        )

        # Capacidade de produção restante (limitada pelo estoque de material)
        capacidade_maxima = 999_999
        if r["peso_gramas"] and float(r["peso_gramas"]) > 0:
            estoque_g = (
                float(r["estoque_material_atual"]) * 1000
                if r["unidade_material"] == "kg"
                else float(r["estoque_material_atual"])
            )
            capacidade_maxima = int(estoque_g / float(r["peso_gramas"]))

        # Dias de autonomia ao ritmo de vendas atual
        if vendas > 0:
            taxa_diaria   = vendas / 7
            dias_estoque  = round(capacidade_maxima / taxa_diaria)
        else:
            dias_estoque  = 999  # sem vendas = estoque "infinito"

        historico_ia = None
        if r["ultima_acao"]:
            historico_ia = {
                "acao_passada": r["ultima_acao"],
                "detalhe":      r["ultimo_detalhe"],
                "projetado_na_epoca": r["ultima_projecao"],
            }

        dossie.append({
            "item_id":   r["item_id"],
            "model_id":  r["model_id"],
            "nome_produto":      r["nome_atual"],
            "nome_variacao":     r["nome_variacao"],
            "preco_atual":       preco,
            "custo_fab_real":    round(custo_fab, 2),

            "vendas_7d_reais":              vendas,
            "tendencia_vendas_WoW_perc":    tendencia_perc,
            "taxa_abandono_carrinho_perc":  taxa_abandono,
            "lucro_liquido_real_7d":        round(lucro_operacional, 2),

            "REPUTACAO_estrelas":               float(r["estrelas"]),
            "REPUTACAO_curtidas_favoritos":     r["curtidas_favoritos"],
            "LOGISTICA_capacidade_material_restante": capacidade_maxima,
            "LOGISTICA_dias_estoque_restante":  dias_estoque,

            "TRAFEGO_visitas_7d":           visitas,
            "TRAFEGO_adicoes_carrinho_7d":  carrinhos,
            "TRAFEGO_taxa_conversao_perc":  taxa_conversao,

            "ADS_gasto_7d":   round(gasto_ads, 2),
            "ADS_roas_atual": roas_atual,

            "historico_acoes_passadas": historico_ia,
        })

    return dossie


# ==============================================================================
# SEÇÃO 2 — ANÁLISE PRÉVIA SEM LLM (regras determinísticas)
# ==============================================================================

def calcular_score_urgencia(d: dict) -> int:
    """
    Pontua a urgência de um produto de 0 a 100.
    Usado para ordenar o lote antes de enviar à IA — os casos mais críticos
    chegam primeiro e, se houver timeout de RunPod, ao menos foram analisados.
    """
    score = 0

    # Perdendo dinheiro em Ads (ROAS < 1 = gasta mais do que recebe)
    if d.get("ADS_gasto_7d", 0) > 5 and d.get("ADS_roas_atual", 0) < 1:
        score += 40

    # Material acabando em menos de 7 dias ao ritmo atual
    if d.get("LOGISTICA_dias_estoque_restante", 999) < 7:
        score += 35

    # Lucro operacional negativo
    if d.get("lucro_liquido_real_7d", 0) < 0:
        score += 30

    # Queda de vendas > 30 % semana a semana
    if d.get("tendencia_vendas_WoW_perc", 0) < -30:
        score += 25

    # Alta taxa de abandono + muitos favoritos = oportunidade de promoção perdida
    if d.get("taxa_abandono_carrinho_perc", 0) > 70 and d.get("REPUTACAO_curtidas_favoritos", 0) > 50:
        score += 20

    # Sem vendas com gasto em Ads
    if d.get("vendas_7d_reais", 0) == 0 and d.get("ADS_gasto_7d", 0) > 0:
        score += 30

    return min(score, 100)


def calcular_dias_estoque(d: dict) -> int:
    """Retorna quantos dias de material restam ao ritmo de vendas atual."""
    return d.get("LOGISTICA_dias_estoque_restante", 999)


def gerar_alertas_criticos(dossie: list[dict]) -> list[dict]:
    """
    Detecta situações que não precisam de LLM — são matematicamente óbvias.
    Retorna uma lista de alertas para exibir no topo do dashboard.
    """
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


# ==============================================================================
# SEÇÃO 3 — MOTOR PREDITIVO (RUNPOD via LiteLLM Proxy)
# ==============================================================================

def validar_sugestao_ia(dados: dict, analise: dict) -> tuple[bool, str]:
    """
    Fix #8 — camada de segurança em código Python.
    Roda ANTES de exibir o botão de aprovação.
    Não depende do LLM obedecer o prompt.
    Retorna (True, "") se está ok, ou (False, motivo) se deve bloquear.
    """
    preco_atual      = dados.get("preco_atual", 0)
    capacidade_max   = dados.get("LOGISTICA_capacidade_material_restante", 999_999)
    novo_preco       = analise.get("novo_preco_sugerido", preco_atual)
    previsao_vendas  = analise.get("previsao_vendas_7d", 0)

    if novo_preco is None or novo_preco <= 0:
        return False, "Preço sugerido é inválido (zero, negativo ou ausente)."

    if preco_atual > 0:
        variacao = abs(novo_preco - preco_atual) / preco_atual
        if variacao > 0.80:
            return False, (
                f"Variação de {variacao * 100:.0f}% no preço excede o limite "
                f"de segurança de 80%. Ajuste manual necessário."
            )

    if previsao_vendas and capacidade_max < 999_999:
        if previsao_vendas > capacidade_max:
            return False, (
                f"Previsão de {previsao_vendas} un. excede a capacidade de "
                f"fábrica ({capacidade_max} un. de material restante)."
            )

    return True, ""


def chamar_cerebro_runpod_preditivo(lote_json: list[dict]) -> list[dict]:
    """
    Envia o lote ao modelo Qwen 32B no RunPod via LiteLLM Proxy (porta 8000).
    Retorna a lista de análises parseada como JSON.
    """
    prompt_sistema = """
    Você é o Conselho de Administração (CFO, CMO, COO) de uma Fazenda de Impressão 3D na Shopee.
    Realize uma Auditoria Profunda do Lote fornecido baseando-se em microeconomia.

    DIRETRIZES TÁTICAS:
    - COO: "LOGISTICA_capacidade_material_restante" é o teto de produção.
      NUNCA defina "previsao_vendas_7d" acima deste valor.
      Se "LOGISTICA_dias_estoque_restante" < 14, sugira AUMENTAR_PRECO
      para desacelerar vendas e preservar margem até o reabastecimento.
    - CMO: Use TRAFEGO_*, ADS_gasto_7d e ADS_roas_atual para avaliar saúde
      do tráfego pago e orgânico.
      • ROAS < 3× com gasto relevante → reduza preço OU pause ads antes de
        queimar mais orçamento em promoção.
      • Alta REPUTACAO_curtidas_favoritos + vendas baixas + tráfego saudável
        → CRIAR_PROMOCAO (notifica os interessados com push Shopee).
      • taxa_abandono_carrinho_perc > 65% → CRIAR_COMBO para diluir frete.
    - CFO: Maximize "lucro_liquido_real_7d" (já inclui ADS_gasto_7d no cálculo).
      Verifique se custo_fab_real * previsao_vendas_7d cabe dentro da margem.

    AÇÕES PERMITIDAS ("tipo_acao"):
    - "AUMENTAR_PRECO" ou "REDUZIR_PRECO"
    - "CRIAR_PROMOCAO"  (obrigatório o campo "horas_duracao_promocao")
    - "CRIAR_COMBO"
    - "MANTER"

    FORMATO DE SAÍDA (RETORNE APENAS O ARRAY JSON, SEM MARKDOWN):
    [
      {
        "item_id": 123,
        "model_id": 456,
        "tipo_acao": "CRIAR_PROMOCAO",
        "novo_preco_sugerido": 45.90,
        "horas_duracao_promocao": 24,
        "previsao_vendas_7d": 80,
        "previsao_lucro_7d": 500.00,
        "relatorio_cfo_financas": "Margem absorve refugo; queima de 10% segura.",
        "relatorio_cmo_marketing": "ROAS 4.2× e conversão 3.1% saudáveis. 300 favoritos; push de 24h os notificará.",
        "relatorio_coo_operacoes": "Material para 150 peças. Fábrica aguenta.",
        "plano_acao_shopee": ["Ativar promoção relâmpago 24h para converter favoritos."],
        "analise_de_consequencias": "Pico esperado de 15 vendas nas próximas 24h."
      }
    ]
    """
    try:
        response = litellm.completion(
            model="cerebro-dados",
            api_base=LITELLM_BASE,
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user",   "content": f"Auditoria:\n{json.dumps(lote_json, indent=2, ensure_ascii=False)}"},
            ],
            max_tokens=6_000,
            temperature=0.2,
        )
        texto = response.choices[0].message.content.strip()

        # Limpeza robusta de markdown que alguns modelos insistem em adicionar
        texto = re.sub(r"^```(?:json)?", "", texto).rstrip("`").strip()

        match = re.search(r"\[.*\]", texto, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return []

    except json.JSONDecodeError as e:
        st.error(f"IA retornou JSON inválido: {e}")
        return []
    except Exception as e:
        st.error(f"Erro na comunicação com o Cérebro RunPod: {e}")
        return []


def processar_em_lotes(dossie_completo: list[dict], tamanho_lote: int = 8) -> list[dict]:
    """
    Ordena o dossiê por urgência (maior score primeiro) e envia à IA em lotes.
    Produtos mais críticos são processados primeiro — caso haja timeout no
    RunPod, os menos urgentes ficam de fora, não os críticos.
    """
    # Ordena por score de urgência (decrescente) antes de fatiar
    dossie_ordenado = sorted(
        dossie_completo,
        key=calcular_score_urgencia,
        reverse=True,
    )

    lotes = [
        dossie_ordenado[i : i + tamanho_lote]
        for i in range(0, len(dossie_ordenado), tamanho_lote)
    ]

    resultados_finais = []
    barra = st.progress(0, text="Iniciando análise...")

    for i, lote in enumerate(lotes):
        barra.progress(
            (i + 1) / len(lotes),
            text=f"⏳ Conselho auditando lote {i + 1} de {len(lotes)} "
                 f"({len(lote)} produtos)...",
        )

        resultado_lote = chamar_cerebro_runpod_preditivo(lote)

        for rec in resultado_lote:
            original = next(
                (d for d in lote
                 if d["item_id"] == rec.get("item_id")
                 and d["model_id"] == rec.get("model_id")),
                None,
            )
            if original:
                rec["dados_atuais"]     = original
                rec["score_urgencia"]   = calcular_score_urgencia(original)
                rec["dias_estoque"]     = calcular_dias_estoque(original)
            resultados_finais.append(rec)

    barra.empty()
    return resultados_finais


# ==============================================================================
# SEÇÃO 4 — PERSISTÊNCIA
# ==============================================================================

def salvar_log_acao(
    item_id: int,
    model_id: int,         # Fix #7 — novo parâmetro
    tipo_acao: str,
    detalhe: str,
    impacto_json: dict,
    status: str,
):
    """Registra a decisão aprovada no Diário de Bordo (agora por variação)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO log_acoes_shopee
                    (item_id, model_id, tipo_acao, detalhe_acao, impacto_projetado, status_api)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (item_id, model_id, tipo_acao, detalhe, json.dumps(impacto_json), status),
            )


# ==============================================================================
# SEÇÃO 5 — INTERFACE DO USUÁRIO
# ==============================================================================

st.title("🧠 Conselho de Administração IA & Atuador")
st.markdown(
    "Auditoria profunda de **Finanças, Marketing e Fábrica** com predição de "
    "cenários e gatilhos de Notificação (Push) na Shopee."
)

# ─── Botão de disparo ────────────────────────────────────────────────────────
if st.button("⚡ Executar Auditoria Profunda (RunPod)", type="primary"):
    with st.status("Acordando o Conselho de IA...", expanded=True) as status_boot:
        st.write("📊 Lendo Data Warehouse e calculando métricas...")
        dossie = gerar_dossie_produtos_com_memoria()

        if not dossie:
            st.warning(
                "Nenhum produto ativo encontrado. Execute a Sincronização primeiro."
            )
            st.stop()

        st.write(f"✅ {len(dossie)} variações carregadas. Enviando ao RunPod...")
        st.session_state.analises_preditivas = processar_em_lotes(dossie)
        status_boot.update(label="Auditoria concluída!", state="complete", expanded=False)
    st.rerun()

st.divider()

# ─── Exibe resultados ─────────────────────────────────────────────────────────
if "analises_preditivas" not in st.session_state or not st.session_state.analises_preditivas:
    st.info("Clique no botão acima para iniciar a auditoria do Conselho de IA.")
    st.stop()

analises = st.session_state.analises_preditivas

# ── Dashboard de KPIs agregados ───────────────────────────────────────────────
st.subheader("📊 Visão Geral da Loja (últimos 7 dias)")

total_lucro    = sum(a.get("dados_atuais", {}).get("lucro_liquido_real_7d", 0) for a in analises)
total_vendas   = sum(a.get("dados_atuais", {}).get("vendas_7d_reais", 0) for a in analises)
total_gasto    = sum(a.get("dados_atuais", {}).get("ADS_gasto_7d", 0) for a in analises)
produtos_criticos = sum(1 for a in analises if a.get("score_urgencia", 0) >= 40)
dias_min_estoque  = min(
    (a.get("dias_estoque", 999) for a in analises if a.get("dias_estoque", 999) < 999),
    default=999,
)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("💰 Lucro Líquido Total", f"R$ {total_lucro:,.2f}")
c2.metric("📦 Vendas Totais", f"{total_vendas} un.")
c3.metric("📣 Gasto Total em Ads", f"R$ {total_gasto:,.2f}")
c4.metric(
    "🚨 Produtos Críticos",
    f"{produtos_criticos}",
    delta=f"de {len(analises)} analisados",
    delta_color="inverse",
)
c5.metric(
    "⏳ Menor Autonomia de Material",
    f"{dias_min_estoque if dias_min_estoque < 999 else '∞'} dias",
    delta_color="inverse" if dias_min_estoque < 14 else "normal",
)

# ── Alertas críticos (sem LLM) ────────────────────────────────────────────────
todos_os_dados = [a.get("dados_atuais", {}) for a in analises if a.get("dados_atuais")]
alertas = gerar_alertas_criticos(todos_os_dados)

if alertas:
    with st.expander(f"⚠️ {len(alertas)} alertas críticos detectados automaticamente", expanded=True):
        for alerta in alertas:
            st.error(f"**{alerta['nivel']} — {alerta['produto']}**\n\n{alerta['mensagem']}")

st.divider()

# ── Relatórios por produto ─────────────────────────────────────────────────────
st.subheader("📋 Relatórios Executivos por Produto")

for analise in analises:
    dados = analise.get("dados_atuais", {})
    if not dados:
        continue

    acao          = analise.get("tipo_acao", "MANTER")
    score         = analise.get("score_urgencia", 0)
    dias_mat      = analise.get("dias_estoque", 999)
    preco_atual   = dados["preco_atual"]
    novo_preco    = analise.get("novo_preco_sugerido", preco_atual)

    icon_acao = {
        "AUMENTAR_PRECO":  "📈",
        "REDUZIR_PRECO":   "📉",
        "CRIAR_PROMOCAO":  "🔥",
        "CRIAR_COMBO":     "🛍️",
    }.get(acao, "⚖️")

    badge_urgencia = (
        "🔴 URGENTE" if score >= 40
        else "🟡 ATENÇÃO" if score >= 20
        else "🟢 OK"
    )
    dias_str = f"⏳ {dias_mat}d mat." if dias_mat < 999 else ""

    with st.expander(
        f"{icon_acao} {dados['nome_produto']} · {dados.get('nome_variacao', '')} "
        f"| {acao} | {badge_urgencia} {dias_str}"
    ):

        # ── Abas do conselho ──────────────────────────────────────────────────
        st.markdown("### 🕵️ Auditoria do Conselho")
        tab_cfo, tab_cmo, tab_coo = st.tabs(
            ["💰 CFO (Finanças)", "🎯 CMO (Tráfego & Ads)", "🏭 COO (Operações)"]
        )

        with tab_cfo:
            st.info(analise.get("relatorio_cfo_financas", "Análise financeira não disponível."))
            custo = dados.get("custo_fab_real", 0)
            margem = ((preco_atual - custo) / preco_atual * 100) if preco_atual > 0 else 0
            st.caption(
                f"Custo de Fábrica (c/ refugo): **R$ {custo:.2f}** | "
                f"Margem Bruta: **{margem:.1f}%** | "
                f"Lucro Líquido 7d: **R$ {dados.get('lucro_liquido_real_7d', 0):.2f}**"
            )

        with tab_cmo:
            st.success(analise.get("relatorio_cmo_marketing", "Análise de marketing não disponível."))
            st.caption(
                f"⭐ {dados.get('REPUTACAO_estrelas', 0)} | "
                f"❤️ {dados.get('REPUTACAO_curtidas_favoritos', 0)} favoritos | "
                f"🛒 Abandono: {dados.get('taxa_abandono_carrinho_perc', 0):.1f}% | "
                f"📈 Conversão: {dados.get('TRAFEGO_taxa_conversao_perc', 0):.2f}% | "
                f"ROAS: {dados.get('ADS_roas_atual', 0):.1f}×"
            )

        with tab_coo:
            st.warning(analise.get("relatorio_coo_operacoes", "Análise operacional não disponível."))
            dias_label = f"{dias_mat} dias" if dias_mat < 999 else "estoque não mapeado"
            st.caption(
                f"🏭 Capacidade restante: **{dados.get('LOGISTICA_capacidade_material_restante', 0)} un.** "
                f"| Autonomia ao ritmo atual: **{dias_label}** "
                f"| Estoque Shopee: **{dados.get('estoque_na_shopee', 0)} un.**"
            )

        # ── Feedback Loop ─────────────────────────────────────────────────────
        hist = dados.get("historico_acoes_passadas")
        if hist:
            st.markdown("---")
            st.markdown("### 🔄 Feedback Loop (Aprendizado da IA)")
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown(f"**Ação anterior:** {hist.get('acao_passada', 'N/A')}")
                st.markdown(f"**Detalhe:** {hist.get('detalhe', '')}")
                st.markdown(f"**Projeção na época:** {hist.get('projetado_na_epoca', {})}")
            with col_b:
                st.markdown("**Realidade atual (7 dias):**")
                st.metric("Vendas reais", f"{dados.get('vendas_7d_reais', 0)} un.")
                st.metric("Lucro real", f"R$ {dados.get('lucro_liquido_real_7d', 0):.2f}")

        # ── Projeção de cenário ───────────────────────────────────────────────
        st.markdown("---")
        st.markdown("### 📊 Projeção de Cenário (Próximos 7 Dias)")

        c1, c2, c3 = st.columns(3)
        var_preco = ((novo_preco - preco_atual) / preco_atual * 100) if preco_atual > 0 else 0
        c1.metric(
            "Ajuste de Preço",
            f"R$ {preco_atual:.2f} → R$ {novo_preco:.2f}",
            f"{var_preco:+.1f}%",
        )

        vendas_atuais = dados["vendas_7d_reais"]
        vendas_proj   = analise.get("previsao_vendas_7d", vendas_atuais)
        delta_v = (
            f"+{vendas_proj} un." if vendas_atuais == 0
            else f"{(vendas_proj - vendas_atuais) / vendas_atuais * 100:+.1f}%"
        )
        c2.metric("Volume Projetado", f"{vendas_proj} un.", delta_v)

        lucro_atual = dados["lucro_liquido_real_7d"]
        lucro_proj  = analise.get("previsao_lucro_7d", lucro_atual)
        delta_l = (
            f"R$ {lucro_proj:.2f}" if lucro_atual == 0
            else f"{(lucro_proj - lucro_atual) / abs(lucro_atual) * 100:+.1f}%"
        )
        c3.metric("Lucro Projetado", f"R$ {lucro_proj:.2f}", delta_l)

        # ── Plano de ação ─────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("### 🚀 Plano de Ação Estratégico")
        for passo in (analise.get("plano_acao_shopee") or []):
            st.markdown(f"- {passo}")
        st.markdown(f"**🔮 Consequência:** {analise.get('analise_de_consequencias', '')}")

        # ── Botão Atuador com camada de segurança (Fix #8) ───────────────────
        if acao != "MANTER":
            valido, motivo = validar_sugestao_ia(dados, analise)

            if not valido:
                st.error(
                    f"🚫 Sugestão bloqueada pela camada de segurança:\n\n**{motivo}**\n\n"
                    "Edite manualmente os valores e aplique via pgAdmin se necessário."
                )
            else:
                # Tudo validado — exibe o botão
                duracao = analise.get("horas_duracao_promocao", 24)

                if acao == "CRIAR_PROMOCAO":
                    texto_botao = f"🔥 Aprovar Promoção Flash: R$ {novo_preco:.2f} por {duracao}h"
                elif acao == "CRIAR_COMBO":
                    texto_botao = "🛍️ Aprovar Combo Promocional na Shopee"
                else:
                    texto_botao = f"✅ Aprovar Alteração: R$ {preco_atual:.2f} → R$ {novo_preco:.2f}"

                if st.button(
                    texto_botao,
                    key=f"btn_{dados['item_id']}_{dados['model_id']}",
                    use_container_width=True,
                ):
                    with st.spinner("Conectando aos satélites da Shopee..."):
                        sucesso, msg = False, "Ação em desenvolvimento."

                        if acao == "CRIAR_PROMOCAO":
                            sucesso, msg = criar_promocao_shopee(
                                dados["item_id"], dados["model_id"], novo_preco, duracao
                            )
                        elif acao in ("AUMENTAR_PRECO", "REDUZIR_PRECO"):
                            sucesso, msg = atualizar_preco_shopee(
                                dados["item_id"], dados["model_id"], novo_preco
                            )
                        elif acao == "CRIAR_COMBO":
                            sucesso, msg = criar_combo_shopee(
                                dados["item_id"], percentual_desconto=10
                            )

                        impacto_log = {
                            "vendas_projetadas": vendas_proj,
                            "lucro_projetado":   lucro_proj,
                            "estrategia":        acao,
                        }

                        # Fix #7 — grava model_id no log
                        if sucesso:
                            salvar_log_acao(
                                dados["item_id"],
                                dados["model_id"],
                                acao,
                                f"Aprovado com alvo R$ {novo_preco:.2f}",
                                impacto_log,
                                "SUCESSO",
                            )
                            st.success(msg)
                            if acao != "CRIAR_COMBO":
                                st.balloons()
                        else:
                            salvar_log_acao(
                                dados["item_id"],
                                dados["model_id"],
                                acao,
                                f"Falha — alvo R$ {novo_preco:.2f}",
                                impacto_log,
                                "ERRO_API",
                            )
                            st.error(f"Erro na API Shopee: {msg}")
