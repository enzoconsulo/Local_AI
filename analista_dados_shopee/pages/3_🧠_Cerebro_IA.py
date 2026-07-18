"""
pages/3_🧠_Cerebro_IA.py
========================
Conselho de Administração IA (CFO, CMO, COO) + Atuador Shopee.

Esta página contém APENAS interface. Toda a lógica vive no pacote `cerebro/`:
extração (dossie), heurísticas determinísticas, memória analítica, motor
OpenAI, atuador e orquestração. Consulte cerebro/__init__.py para o mapa.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from utils.db_pool import get_connection
from utils.padronizar_texto import padronizar_texto
from cerebro import config, orquestrador
from cerebro.atuador import processar_acao_api, verificar_status_promocao
from cerebro.config import classificar_modo_execucao, explicar_acao, rotulo_acao
from cerebro.heuristicas import (
    classificar_confianca_evidencia,
    gerar_alertas_criticos,
    intervalo_demanda_exploratorio,
    sugerir_alavancas_vendas,
)
from cerebro.motor_ia import validar_sugestao_ia

st.set_page_config(
    page_title="Cérebro Analítico & Atuador",
    page_icon="🧠",
    layout="wide"
)

from utils.ui import aplicar_estilo, cabecalho, nota
aplicar_estilo()


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS DE INTERFACE
# ══════════════════════════════════════════════════════════════════════════════

def _serie_numerica(df: pd.DataFrame, coluna: str) -> pd.Series:
    """Retorna uma série numérica segura, inclusive para auditorias antigas no cache."""
    if coluna not in df.columns:
        return pd.Series(0.0, index=df.index, dtype="float64")
    return pd.to_numeric(df[coluna], errors="coerce").fillna(0.0)


def _expandir_dados_atuais(df: pd.DataFrame) -> pd.DataFrame:
    """Achata o dicionário dados_atuais em colunas, priorizando a fonte observada."""
    if 'dados_atuais' in df.columns:
        dados_expandidos = df['dados_atuais'].apply(lambda x: pd.Series(x if isinstance(x, dict) else {}))
        df = pd.concat([df.drop(columns=['dados_atuais']), dados_expandidos], axis=1)
    # Campos de identificação também existem no resultado da IA e no dossiê expandido.
    # Mantemos a versão do dossiê (a fonte observada) para filtros e cálculos consistentes.
    return df.loc[:, ~df.columns.duplicated(keep='last')]


def salvar_cache_auditoria():
    orquestrador.salvar_cache_em_disco(
        st.session_state.get("horizonte_auditoria", "7d") or "7d",
        st.session_state.analises_preditivas,
    )


def _soma_com_escudo(variacoes: list[dict], campo: str):
    """Soma um campo rateado entre as variações preservando o escudo de nulos:
    None em todas = dado não coletado (retorna None, não zero)."""
    valores = [v.get("dados_atuais", {}).get(campo) for v in variacoes]
    numericos = [float(x) for x in valores if x is not None]
    return sum(numericos) if numericos else None


def _fmt_qtd(valor) -> str:
    return f"{int(valor):,}".replace(",", ".") if valor is not None else "—"


def _float_ou_none(valor):
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


# ── Status de execução por horizonte (visibilidade de custo e cadência) ───────

# Preço por 1M de tokens (entrada, saída) — usado só para exibir o custo real
# da última auditoria; se o modelo configurado não estiver aqui, mostra tokens.
PRECOS_MODELO_USD_1M = {
    "gpt-5.6-luna": (1.00, 6.00),
    "gpt-5.6-terra": (2.50, 15.00),
    "gpt-5.6-sol": (5.00, 30.00),
    "gpt-5.4": (2.50, 15.00),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.5": (5.00, 30.00),
}

CADENCIA_SUGERIDA_DIAS = {"7d": 7, "30d": 30}


def _fmt_milhar(numero: int) -> str:
    return f"{int(numero):,}".replace(",", ".")


@st.cache_data(ttl=60, show_spinner=False)
def _consultar_ultima_execucao_db(horizonte_dias: int) -> dict | None:
    """Data real e telemetria da última auditoria do horizonte (migração 11+).

    O mtime do cache em disco não serve como data da auditoria: aprovar uma ação
    regrava o arquivo. A fonte confiável é ia_execucoes_analiticas.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT atualizado_em, status, resumo_executivo
                    FROM ia_execucoes_analiticas
                    WHERE horizonte_dias = %s AND status IN ('CONCLUIDA', 'PARCIAL')
                    ORDER BY atualizado_em DESC NULLS LAST
                    LIMIT 1;
                """, (horizonte_dias,))
                linha = cur.fetchone()
        if not linha:
            return None
        quando = linha[0]
        if quando is not None and quando.tzinfo is not None:
            quando = quando.astimezone().replace(tzinfo=None)
        resumo = linha[2] if isinstance(linha[2], dict) else {}
        return {"quando": quando, "status": linha[1], "telemetria": resumo.get("telemetria_ia") or {}}
    except Exception:
        return None


@st.cache_data(ttl=120, show_spinner=False)
def _ultima_sincronizacao_dw() -> datetime | None:
    """Fim de coleta mais recente do DW — diz se existe dado novo desde a última auditoria."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT MAX(data_fim_coleta) FROM sys_controle_sync WHERE status = 'SUCESSO';")
                linha = cur.fetchone()
        valor = linha[0] if linha else None
        if valor is not None and not isinstance(valor, datetime):
            valor = datetime.combine(valor, datetime.min.time())
        return valor
    except Exception:
        return None


def _composicao_cache_horizonte(horizonte: str) -> dict | None:
    """Conta, no cache em disco, como cada SKU da última auditoria foi tratado."""
    cache = config.CACHE_AUDITORIA_7D if horizonte == "7d" else config.CACHE_AUDITORIA_30D
    if not cache.exists():
        return None
    try:
        with open(cache, "r", encoding="utf-8") as arquivo:
            resultados = json.load(arquivo)
    except Exception:
        return None
    fantasmas = sum(1 for r in resultados if r.get("cluster_mercado") == "Baixa atividade observada")
    economicos = sum(1 for r in resultados if r.get("analise_local"))
    falhas = sum(1 for r in resultados if r.get("falha_modelo_externo"))
    return {
        "mtime": datetime.fromtimestamp(cache.stat().st_mtime),
        "total": len(resultados),
        "fantasmas": fantasmas,
        "economicos": economicos,
        "falhas": falhas,
        "ia": max(0, len(resultados) - fantasmas - economicos - falhas),
    }


def _painel_status_horizonte(horizonte: str, ultima_sync: datetime | None) -> None:
    """Mostra quando o horizonte rodou, como cada SKU foi tratado e se vale rodar agora."""
    cadencia = CADENCIA_SUGERIDA_DIAS[horizonte]
    execucao = _consultar_ultima_execucao_db(7 if horizonte == "7d" else 30)
    composicao = _composicao_cache_horizonte(horizonte)

    quando = (execucao or {}).get("quando") or (composicao["mtime"] if composicao else None)
    if quando is None:
        st.info(
            "Nunca executada. Comece por aqui: este diagnóstico constrói a memória estratégica que a análise de 7 dias reutiliza."
            if horizonte == "30d"
            else "Nunca executada. Rode primeiro o diagnóstico de 30 dias; depois use esta análise no dia a dia.",
            icon="🆕",
        )
        return

    dias = max(0, (datetime.now() - quando).days)
    rotulo_idade = "hoje" if dias == 0 else "ontem" if dias == 1 else f"há {dias} dias"
    linhas = [f"Última execução: **{quando:%d/%m/%Y %H:%M}** ({rotulo_idade})"]

    if composicao:
        partes = [f"🧠 {composicao['ia']} SKU(s) pela IA"]
        if composicao["fantasmas"]:
            partes.append(f"🏜️ {composicao['fantasmas']} sem atividade → local (R$ 0)")
        if composicao["economicos"]:
            partes.append(f"💸 {composicao['economicos']} evidência baixa → local (R$ 0)")
        if composicao["falhas"]:
            partes.append(f"⚠️ {composicao['falhas']} com falha de IA")
        linhas.append(" · ".join(partes))

    telemetria = (execucao or {}).get("telemetria") or {}
    if telemetria.get("chamadas"):
        tokens_in = int(telemetria.get("prompt_tokens", 0) or 0)
        tokens_out = int(telemetria.get("completion_tokens", 0) or 0)
        precos = PRECOS_MODELO_USD_1M.get(str(telemetria.get("modelo", "")))
        custo_txt = (
            f" ≈ **US$ {(tokens_in * precos[0] + tokens_out * precos[1]) / 1_000_000:.2f}**"
            if precos else ""
        )
        linhas.append(
            f"Custo real: {telemetria['chamadas']} chamada(s) · "
            f"{_fmt_milhar(tokens_in)} tokens de entrada · {_fmt_milhar(tokens_out)} de saída{custo_txt}"
        )
    elif telemetria:
        linhas.append("Custo real: R$ 0 — tudo foi resolvido por cache, checkpoint ou análise local.")

    st.markdown("  \n".join(linhas))

    if composicao and composicao["falhas"]:
        st.warning(
            f"{composicao['falhas']} SKU(s) ficaram com fallback por falha da IA — rode novamente: "
            "somente eles serão reanalisados (sem custo duplicado).",
            icon="⏰",
        )
    elif dias >= cadencia:
        st.warning(f"Recomendado rodar agora — a última execução foi {rotulo_idade} e a cadência sugerida é a cada {cadencia} dias.", icon="⏰")
    elif ultima_sync is not None and ultima_sync <= quando:
        st.success("Em dia. Nenhum dado novo foi sincronizado desde a última execução — rodar agora não mudaria a leitura.", icon="✅")
    else:
        st.success(f"Em dia. Próxima execução recomendada a partir de {quando + timedelta(days=cadencia):%d/%m}.", icon="✅")


def _render_parecer_variacao(analise_var: dict):
    """Dossiê completo de UMA variação: indicadores medidos, ação, pareceres e planos."""
    dados_var = analise_var.get("dados_atuais", {})
    acao = analise_var.get("tipo_acao", "MANTER")
    confianca_var, leitura_var, _ = classificar_confianca_evidencia(dados_var)

    margem_rs = _float_ou_none(dados_var.get("FINANCEIRO_margem_unitaria_reais"))
    margem_pc = _float_ou_none(dados_var.get("FINANCEIRO_margem_unitaria_perc"))
    acos = _float_ou_none(dados_var.get("ADS_acos_medio")) or 0.0
    gasto = _float_ou_none(dados_var.get("ADS_gasto_7d")) or 0.0
    share = _float_ou_none(dados_var.get("PORTFOLIO_share_variacao_30d_perc"))
    abc = dados_var.get("PORTFOLIO_curva_abc")
    dias_anuncio = dados_var.get("LOGISTICA_dias_estoque_shopee")

    i1, i2, i3, i4 = st.columns(4)
    i1.metric(
        "Margem unitária", f"R$ {margem_rs:.2f}" if margem_rs is not None else "—",
        delta=f"{margem_pc:.0f}% do preço" if margem_pc is not None else None, delta_color="off",
        help="Preço − taxa Shopee − custo de fabricação. Em % do preço, é o ACOS de equilíbrio.",
    )
    if gasto > 0 and margem_pc and acos > 0:
        rentavel = acos <= margem_pc
        i2.metric(
            "ACOS × equilíbrio", f"{acos:.0f}% / {margem_pc:.0f}%",
            delta="ads rentável" if rentavel else "consumindo margem",
            delta_color="normal" if rentavel else "inverse",
            help="ACOS da campanha contra a margem unitária em % do preço. Acima do equilíbrio, cada venda por ads sai no prejuízo.",
        )
    else:
        i2.metric("ACOS × equilíbrio", "—", delta="sem gasto em ads no período", delta_color="off")
    i3.metric(
        "Participação no anúncio", f"{share:.0f}%" if share is not None else "—",
        delta=f"Curva {abc}" if abc else None, delta_color="off",
        help="Fatia desta variação nas vendas de 30 dias do anúncio. Curva ABC pela contribuição ao lucro mensal da loja.",
    )
    if dias_anuncio in (None, 999):
        rotulo_estoque = "confortável"
    else:
        rotulo_estoque = f"{int(dias_anuncio)} dia(s)"
    i4.metric(
        "Estoque do anúncio", rotulo_estoque,
        delta=f"{int(dados_var.get('estoque_shopee_hoje', 0) or 0)} un. publicadas", delta_color="off",
        help="Estoque publicado ÷ ritmo de vendas de 7 dias. Anúncio zerado sai da busca e perde ranking.",
    )

    st.markdown(
        f"**Ação recomendada:** {rotulo_acao(acao)} &nbsp;·&nbsp; Evidência **{confianca_var}** — "
        f"{padronizar_texto(leitura_var)}"
    )
    if dados_var.get("PROMO_ativa_tipo"):
        st.warning(
            f"🏷️ Promoção Shopee vigente ({dados_var['PROMO_ativa_tipo']}) neste SKU: o preço atual "
            "é promocional — não crie promoção nem reduza preço por cima; reavalie após o término.",
            icon="🏷️",
        )
    st.markdown(f"**Recomendação executiva:** {padronizar_texto(analise_var.get('recomendacao_executiva', 'N/A'))}")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.info(f"**💰 CFO — Finanças**\n\n{padronizar_texto(analise_var.get('relatorio_cfo_financas', 'N/A'))}")
    with c2:
        st.success(f"**🎯 CMO — Marketing**\n\n{padronizar_texto(analise_var.get('relatorio_cmo_marketing', 'N/A'))}")
    with c3:
        st.warning(f"**🏭 COO — Operações**\n\n{padronizar_texto(analise_var.get('relatorio_coo_operacoes', 'N/A'))}")

    plano7 = analise_var.get("plano_curto_prazo_7d") or analise_var.get("plano_acao_shopee") or []
    plano30 = analise_var.get("plano_longo_prazo_30d") or []
    if plano7 or plano30:
        p1, p2 = st.columns(2)
        with p1:
            st.markdown("**Plano · 7 dias**")
            for passo in plano7:
                st.write(f"• {padronizar_texto(str(passo))}")
        with p2:
            st.markdown("**Plano · 30 dias**")
            for passo in plano30:
                st.write(f"• {padronizar_texto(str(passo))}")
    if analise_var.get("analise_de_consequencias"):
        st.caption(f"Consequência esperada: {padronizar_texto(analise_var['analise_de_consequencias'])}")


# ══════════════════════════════════════════════════════════════════════════════
# ESTRUTURA PRINCIPAL DA TELA
# ══════════════════════════════════════════════════════════════════════════════

cabecalho("🧠", "Conselho C-Level & Atuador IA",
           "Auditoria profunda de Finanças, Marketing e Fábrica, com predição de cenários e execução direta na Shopee.")

# Inicialização: restaura a auditoria mais recente do disco
if "analises_preditivas" not in st.session_state:
    analises_cache, horizonte_cache, id_execucao_cache = orquestrador.carregar_ultima_auditoria()
    st.session_state.analises_preditivas = analises_cache
    st.session_state.horizonte_auditoria = horizonte_cache
    if id_execucao_cache:
        st.session_state.id_execucao_analitica = id_execucao_cache

# ─── Disparo da auditoria ─────────────────────────────────────────────────────
with st.container(border=True):
    st.subheader("Atualizar diagnóstico")
    st.caption(
        "A análise de **7 dias** é operacional e recorrente; a de **30 dias** é estratégica e mais "
        "completa. Com volume moderado de vendas, rodar além da cadência sugerida não melhora a "
        "leitura — de um dia para o outro entra pouco dado novo. O painel abaixo mostra quando "
        "cada análise rodou, quanto custou e se vale a pena rodar agora."
    )

    ultima_sync_dw = _ultima_sincronizacao_dw()
    col_7d, col_30d = st.columns(2, gap="medium")
    with col_7d, st.container(border=True):
        st.markdown("#### ⚙️ Operacional · 7 dias")
        st.caption(
            "Sinais recentes, intervenção tática. Cadência sugerida: **1× por semana** — "
            "ou logo após mudar preço/ads ou receber um alerta crítico."
        )
        _painel_status_horizonte("7d", ultima_sync_dw)
        executar_7d = st.button(
            "Atualizar análise de 7 dias", type="primary", use_container_width=True,
            help="Envia somente os sinais recentes ao modelo. É o fluxo recomendado para uso recorrente.",
        )
    with col_30d, st.container(border=True):
        st.markdown("#### 🧭 Estratégico · 30 dias")
        st.caption(
            "Dossiê mensal completo com memória estratégica. Cadência sugerida: **1× por mês** — "
            "na primeira execução e após mudanças grandes de estratégia."
        )
        _painel_status_horizonte("30d", ultima_sync_dw)
        executar_30d = st.button(
            "Executar diagnóstico de 30 dias", use_container_width=True,
            help="Envia o dossiê mensal completo. Use na primeira execução e em revisões estratégicas.",
        )

    analise_completa = st.toggle(
        "Análise completa: enviar também os SKUs de evidência baixa à IA",
        value=False,
        help=(
            "Desligado (padrão): SKUs com pouco histórico e sem urgência recebem parecer local "
            "determinístico, sem custo de IA. Ligue quando quiser a opinião do Conselho sobre "
            "produtos que vendem pouco e você não sabe por quê. Produtos sem NENHUMA atividade "
            "continuam resolvidos localmente em qualquer modo — a IA não teria dado algum para analisar."
        ),
    )
    with st.expander("O que vai e o que NÃO vai para a IA — controle de custo em 4 camadas"):
        st.markdown(f"""
1. **🏜️ Sem atividade ("fantasmas")** — produto com cobertura de dados e ≤ 10 visitas, R$ 0 de ads e 0 vendas em 30 dias: recebe parecer local completo (SEO, foto de capa, impulso gratuito, teste mínimo de descoberta). **Nunca vai à IA, em nenhum modo** — não há dado para o modelo interpretar.
2. **💸 Modo econômico** — SKU de evidência **baixa** e urgência **< 40**: parecer determinístico local (a execução automática já seria bloqueada para ele de qualquer forma). Controlado pelo seletor acima. **Urgência ≥ 40 sempre vai à IA, mesmo com evidência baixa** — produto indo mal com sinal real (prejuízo, ads sem retorno, queda forte de vendas) nunca fica de fora.
3. **♻️ Cache semântico + checkpoint** — SKU cujos dados não mudaram desde a última auditoria reutiliza a análise anterior; auditoria interrompida retoma de onde parou. Só o produto que **mudou** gera custo.
4. **🧠 IA de verdade** — apenas o restante é enviado (7d: `{config.OPENAI_MODEL_7D}` · 30d: `{config.OPENAI_MODEL_30D}`). Custo típico: ~US$ 0,004/SKU no 7d e ~US$ 0,03/SKU no 30d.
        """)

    horizonte_escolhido = "7d" if executar_7d else "30d" if executar_30d else None
    if horizonte_escolhido:
        titulo = "análise operacional de 7 dias" if horizonte_escolhido == "7d" else "diagnóstico estratégico de 30 dias"
        with st.status(f"Iniciando {titulo}...", expanded=True) as status_boot:
            resultados_ia = orquestrador.executar_auditoria_por_horizonte(
                horizonte_escolhido, status_boot, modo_economico=not analise_completa,
            )
            st.session_state.analises_preditivas = resultados_ia
            st.session_state.horizonte_auditoria = horizonte_escolhido
            status_boot.update(label=f"{titulo.capitalize()} concluído!", state="complete", expanded=False)
        _consultar_ultima_execucao_db.clear()
        _ultima_sincronizacao_dw.clear()
        st.rerun()

analises = st.session_state.analises_preditivas
if not analises:
    st.warning("Ainda não há uma auditoria carregada. Use um dos botões acima — na primeira vez, prefira o **diagnóstico estratégico de 30 dias**.")
    st.stop()

# ─── Preparação do DataFrame ──────────────────────────────────────────────────
df_analises = _expandir_dados_atuais(pd.DataFrame(analises))

if 'nome_produto' in df_analises.columns:
    df_analises['categoria'] = df_analises.get('nome_produto', '').astype(str).str.split().str[0]

# A auditoria mistura fatos observados, inferências e texto do modelo. Estas colunas
# tornam a qualidade da base visível antes de qualquer decisão operacional.
for coluna in [
    'vendas_7d_reais', 'vendas_30d_macro', 'TRAFEGO_visitas_7d', 'visitas_30d_macro',
    'TRAFEGO_adicoes_carrinho_7d', 'ADS_gasto_7d', 'lucro_liquido_real_7d',
    'taxa_cancelamento_7d_perc', 'score_urgencia', 'dias_estoque',
    'preco_tendencia_7d_perc', 'elasticidade_preco_volume'
]:
    df_analises[coluna] = _serie_numerica(df_analises, coluna)

evidencias = df_analises.apply(
    lambda row: classificar_confianca_evidencia(row.to_dict()), axis=1
)
df_analises[['confianca', 'leitura_evidencia', 'tom_confianca']] = pd.DataFrame(
    evidencias.tolist(), index=df_analises.index
)

with st.container(border=True):
    st.subheader("Filtrar a leitura")
    st.caption("Os filtros alteram apenas o que você vê nesta página; não mudam a auditoria nem enviam alterações à Shopee.")
    opcoes_confianca = ["Alta", "Moderada", "Baixa"]
    filtro_evidencia, filtro_acao, filtro_busca = st.columns([3, 2, 3])
    with filtro_evidencia:
        confiancas_selecionadas = st.multiselect(
            "Força da evidência", opcoes_confianca, default=opcoes_confianca,
            help="Filtra pela qualidade do histórico disponível, não pela confiança do modelo de linguagem."
        )
    with filtro_acao:
        mostrar_apenas_acao = st.toggle("Mostrar só ações", value=False, help="Oculta SKUs cuja recomendação atual é apenas monitorar.")
    with filtro_busca:
        texto_busca = st.text_input("Buscar produto ou SKU", placeholder="Ex.: suporte, preto, 123456")

mascara = df_analises['confianca'].isin(confiancas_selecionadas)
if mostrar_apenas_acao and 'tipo_acao' in df_analises.columns:
    mascara &= df_analises['tipo_acao'].fillna('MANTER').ne('MANTER')
if texto_busca:
    busca = (df_analises.get('nome_produto', pd.Series('', index=df_analises.index)).astype(str)
             + ' ' + df_analises.get('nome_variacao', pd.Series('', index=df_analises.index)).astype(str))
    mascara &= busca.str.contains(texto_busca, case=False, na=False)

df_analises = df_analises.loc[mascara].copy()
ids_visiveis = set(df_analises.get('model_id', pd.Series(dtype='object')).astype(str))
analises = [a for a in analises if str(a.get('model_id', a.get('dados_atuais', {}).get('model_id', ''))) in ids_visiveis]

if df_analises.empty:
    st.info("Nenhum SKU corresponde aos filtros atuais. Ajuste os filtros no painel acima.")
    st.stop()

# ─── Organização em 4 Abas Ergonômicas ────────────────────────────────────────
aba_dashboard, aba_atuador, aba_previsao, aba_dossies = st.tabs([
    "Resumo",
    "Alterações recomendadas",
    "Cenários e previsões",
    "Dossiês e alavancas"
])

# ==============================================================================
# ABA 1: VISÃO EXECUTIVA (KPIs, Categorias e Alertas)
# ==============================================================================
with aba_dashboard:
    nota(
        "Fatos observados (7 dias) são exibidos com contexto de 30 dias. A IA formula hipóteses "
        "de ação; a classificação de evidência indica quando executar, testar em pequena escala "
        "ou somente monitorar.",
        titulo="Leitura responsável",
    )

    # 1. Recuperação dos Dados Globais (sem sofrer cortes dos filtros da tela)
    analises_globais = st.session_state.analises_preditivas
    df_globais = _expandir_dados_atuais(pd.DataFrame(analises_globais))

    # 2. Cálculos GLOBAIS da Loja (remove duplicados de variação para somar Ads do anúncio pai corretamente)
    if 'item_id' in df_globais.columns and 'ADS_gasto_7d_total_anuncio' in df_globais.columns:
        df_unicos_por_anuncio = df_globais.drop_duplicates(subset=['item_id'])
        total_gasto_loja = _serie_numerica(df_unicos_por_anuncio, 'ADS_gasto_7d_total_anuncio').sum()
    else:
        total_gasto_loja = _serie_numerica(df_globais, 'ADS_gasto_7d').sum()

    total_lucro_loja = _serie_numerica(df_globais, 'lucro_liquido_real_7d').sum()
    total_vendas_loja = _serie_numerica(df_globais, 'vendas_7d_reais').sum()
    total_visitas_loja = _serie_numerica(df_globais, 'TRAFEGO_visitas_7d').sum()
    total_carrinhos_loja = _serie_numerica(df_globais, 'TRAFEGO_adicoes_carrinho_7d').sum()
    total_pedidos_loja = _serie_numerica(df_globais, 'PEDIDOS_7d').sum()
    total_cancelamentos_loja = _serie_numerica(df_globais, 'cancelamentos_7d').sum()

    conversao_loja = (total_vendas_loja / total_visitas_loja * 100) if total_visitas_loja else 0
    abandono_loja = ((total_carrinhos_loja - total_vendas_loja) / total_carrinhos_loja * 100) if total_carrinhos_loja else 0
    cancelamento_loja = (total_cancelamentos_loja / total_pedidos_loja * 100) if total_pedidos_loja else 0

    st.subheader("🌐 Visão Global da Loja (Últimos 7 dias)")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Resultado Operacional (Loja)", f"R$ {total_lucro_loja:,.2f}", help="Soma do resultado de todos os SKUs processados na auditoria, não apenas os visíveis.")
    k2.metric("Conversão Global", f"{conversao_loja:.2f}%" if total_visitas_loja else "Sem dado")
    k3.metric("Gasto Total em Ads", f"R$ {total_gasto_loja:,.2f}", help="Soma bruta do gasto dos anúncios originais na Shopee, corrigindo rateios fracionados por SKU.")
    k4.metric("Cancelamento Global", f"{cancelamento_loja:.1f}%" if total_pedidos_loja else "Sem dado")

    st.divider()

    # 3. Cálculos do Recorte Filtrado (os SKUs exibidos neste momento)
    st.subheader("🎯 Recorte Operacional (Métricas dos SKUs filtrados)")
    lucro_visivel = _serie_numerica(df_analises, 'lucro_liquido_real_7d').sum()
    vendas_visiveis = _serie_numerica(df_analises, 'vendas_7d_reais').sum()
    gasto_visivel = _serie_numerica(df_analises, 'ADS_gasto_7d').sum()
    produtos_criticos = sum(1 for a in analises_globais if a.get("score_urgencia", 0) >= 40)
    dias_min_estoque = min((a.get("dias_estoque", 999) for a in analises_globais if a.get("dias_estoque", 999) < 999), default=999)

    with st.container(border=True):
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("💰 Lucro (Filtro)", f"R$ {lucro_visivel:,.2f}")
        c2.metric("📦 Vendas (Filtro)", f"{int(vendas_visiveis)} un.")
        c3.metric("📣 Ads Rateado (Filtro)", f"R$ {gasto_visivel:,.2f}", help="Fração dos custos correspondente APENAS aos SKUs exibidos no momento sob ação.")
        c4.metric("🚨 Críticos (Global)", f"{produtos_criticos}", delta=f"de {len(analises_globais)} avaliados", delta_color="inverse")
        c5.metric("⏳ Autonomia Mínima", f"{dias_min_estoque if dias_min_estoque < 999 else '∞'} dias", delta_color="inverse" if dias_min_estoque < 14 else "normal")

    evidencias_resumo = df_analises['confianca'].value_counts()
    st.caption(f"Evidência dos {len(df_analises)} SKUs filtrados: {evidencias_resumo.get('Alta', 0)} alta, {evidencias_resumo.get('Moderada', 0)} moderada, {evidencias_resumo.get('Baixa', 0)} baixa. Abandono de carrinho observado (global): {abandono_loja:.1f}%")

    st.divider()

    # Médias Macro
    score_urgencia = df_analises.get('score_urgencia', pd.Series([0]))
    taxa_cancel = df_analises.get('taxa_cancelamento_7d_perc', pd.Series([0]))
    lucro_liq = df_analises.get('lucro_liquido_real_7d', pd.Series([0]))

    c_m1, c_m2, c_m3 = st.columns(3)
    c_m1.metric("Itens com Urgência Alta", int((score_urgencia >= 40).sum()))
    c_m2.metric("Taxa Média de Cancelamento", f"{taxa_cancel.mean():.1f}%")
    c_m3.metric("Margem Média Estimada", f"R$ {lucro_liq.mean():.2f}")

    st.markdown("### Fila priorizada de decisão")
    fila_decisao = df_analises.copy()
    fila_decisao['ação'] = fila_decisao.get('tipo_acao', pd.Series('MANTER', index=fila_decisao.index)).fillna('MANTER').map(rotulo_acao)
    fila_decisao['faixa_demanda_7d'] = fila_decisao.apply(
        lambda row: "{}–{} un.".format(*intervalo_demanda_exploratorio(
            row.to_dict(), float(row.get('previsao_vendas_7d', 0) or 0)
        )), axis=1
    )
    fila_decisao['elasticidade_legivel'] = fila_decisao.apply(
        lambda row: "Em promoção" if row.get('PROMO_ativa_tipo')
        else f"{float(row.get('elasticidade_preco_volume', 0)):.2f}" if abs(float(row.get('preco_tendencia_7d_perc', 0))) >= 0.5 and float(row.get('vendas_30d_macro', 0)) >= 5
        else "Não identificável",
        axis=1
    )
    if 'PORTFOLIO_curva_abc' not in fila_decisao.columns:
        fila_decisao['PORTFOLIO_curva_abc'] = '—'
    fila_decisao['PORTFOLIO_curva_abc'] = fila_decisao['PORTFOLIO_curva_abc'].fillna('—')
    fila_decisao = fila_decisao.sort_values(['score_urgencia', 'lucro_liquido_real_7d'], ascending=[False, True])
    colunas_fila = ['nome_produto', 'nome_variacao', 'ação', 'confianca', 'PORTFOLIO_curva_abc', 'score_urgencia', 'lucro_liquido_real_7d', 'faixa_demanda_7d', 'elasticidade_legivel', 'leitura_evidencia']
    st.dataframe(
        fila_decisao[colunas_fila], use_container_width=True, hide_index=True, height=280,
        column_config={
            'nome_produto': 'Produto', 'nome_variacao': 'SKU', 'ação': 'Próxima ação',
            'confianca': 'Evidência',
            'PORTFOLIO_curva_abc': st.column_config.TextColumn('ABC', help='Curva ABC pela contribuição ao lucro de 30 dias: A concentra ~80% do resultado.'),
            'score_urgencia': st.column_config.ProgressColumn('Prioridade', min_value=0, max_value=100, format='%d/100'),
            'lucro_liquido_real_7d': st.column_config.NumberColumn('Resultado 7d', format='R$ %.2f'),
            'faixa_demanda_7d': 'Faixa exploratória (7d)', 'elasticidade_legivel': 'Elasticidade',
            'leitura_evidencia': 'Limite da leitura'
        }
    )
    st.caption("A faixa exploratória não é um intervalo estatístico: ela amplia a incerteza quando o histórico é escasso. Elasticidade só é mostrada quando houve variação material de preço e volume mínimo de dados.")

    col_agregacao, col_alertas = st.columns([6, 4])

    with col_agregacao:
        st.markdown("### 🧩 Agregações por Categoria")
        if 'categoria' in df_analises.columns:
            agregacao_categoria = df_analises.groupby('categoria', dropna=False).agg(
                vendas=('vendas_7d_reais', 'sum'),
                lucro=('lucro_liquido_real_7d', 'sum'),
                gasto_ads=('ADS_gasto_7d', 'sum'),
                urgencia=('score_urgencia', 'mean'),
                cancelamento=('taxa_cancelamento_7d_perc', 'mean')
            ).sort_values(['lucro', 'vendas'], ascending=False)

            st.dataframe(agregacao_categoria.reset_index(), use_container_width=True, hide_index=True)

    with col_alertas:
        st.markdown("### 🚨 Alertas Automáticos")
        # Alertas críticos de regra de negócio
        alertas_fortes = gerar_alertas_criticos([a.get("dados_atuais", {}) for a in analises if a.get("dados_atuais")])
        if alertas_fortes:
            for alerta in alertas_fortes:
                st.error(f"**{alerta['produto']}**: {alerta['mensagem']}", icon="🔴")

        # Alertas operacionais
        alertas_exec = []
        for _, row in df_analises.iterrows():
            nome = f"{row.get('nome_produto', 'Produto')} - {row.get('nome_variacao', '')}".strip()
            if row.get('TRAFEGO_taxa_conversao_perc', 0) < 2 and row.get('ADS_gasto_7d', 0) > 5:
                alertas_exec.append(("Queda de conversão", nome, "Conversão baixa com gasto relevante em ads."))
            if row.get('taxa_cancelamento_7d_perc', 0) > 10:
                alertas_exec.append(("Alto cancelamento", nome, "Taxa acima de 10% no período recente."))

        if alertas_exec:
            for alerta in alertas_exec[:8]:
                st.warning(f"**{alerta[1]}**\n\n{alerta[0]}: {alerta[2]}", icon="⚠️")
        elif not alertas_fortes:
            st.success("Nenhum alerta crítico detectado na operação.")

# ==============================================================================
# ABA 2: ATUADOR (Painel de Aprovação)
# ==============================================================================
with aba_atuador:
    st.subheader("Alterações recomendadas")
    nota(
        "<b>1. Compare</b> o estado atual com o proposto. &nbsp; <b>2. Leia</b> a força da "
        "evidência e a consequência. &nbsp; <b>3. Confirme</b> somente quando a alteração estiver "
        "clara. Nenhum botão é executado sem clique explícito.",
        titulo="Fluxo de confirmação",
    )

    produtos_agrupados = {}
    for analise in analises:
        dados = analise.get("dados_atuais", {})
        if not dados: continue

        iid = dados["item_id"]
        if iid not in produtos_agrupados:
            produtos_agrupados[iid] = {
                "item_id": iid,
                "nome_produto": dados.get("nome_produto", "Produto Desconhecido"),
                "score_max": 0,
                "acoes_pendentes": 0,
                "variacoes": []
            }

        produtos_agrupados[iid]["score_max"] = max(produtos_agrupados[iid]["score_max"], analise.get("score_urgencia", 0))
        if analise.get("tipo_acao") != "MANTER":
            produtos_agrupados[iid]["acoes_pendentes"] += 1
        produtos_agrupados[iid]["variacoes"].append(analise)

    produtos_agrupados = dict(sorted(produtos_agrupados.items(), key=lambda x: (x[1]["acoes_pendentes"] > 0, x[1]["score_max"]), reverse=True))

    sem_acoes = True
    for iid, p in produtos_agrupados.items():
        if p["acoes_pendentes"] == 0:
            continue  # Oculta produtos perfeitos para manter o foco visual

        sem_acoes = False
        score = p["score_max"]
        badge = "🔴 Urgente" if score >= 40 else "🟡 Atenção" if score >= 20 else "🟢 Ok"

        nome_produto_limpo = padronizar_texto(p['nome_produto'])

        with st.expander(f"⚡ {nome_produto_limpo} | {p['acoes_pendentes']} SKUs exigem ação | {badge}", expanded=(score >= 40)):
            var_base = p["variacoes"][0]

            with st.container(border=True):
                motivo_limpo = padronizar_texto(var_base.get('recomendacao_executiva', ''))
                consequencia_limpa = padronizar_texto(var_base.get('analise_de_consequencias', ''))

                st.markdown(f"**🎯 Motivo da Intervenção:** {motivo_limpo}")
                st.caption(f"**Projeção IA:** {consequencia_limpa}")

            st.markdown("#### Grade de Ações")
            for analise_var in p["variacoes"]:
                acao_var = analise_var.get("tipo_acao")
                if acao_var == "MANTER": continue

                dados_var = analise_var.get("dados_atuais", {})
                preco_atual = float(dados_var.get("preco_atual") or 0)
                novo_preco = float(analise_var.get("novo_preco_sugerido") or preco_atual)
                modo_execucao, detalhe_execucao = classificar_modo_execucao(acao_var)
                confianca, leitura_evidencia, _ = classificar_confianca_evidencia(dados_var)
                efeito_acao, orientacao_acao = explicar_acao(acao_var)

                nome_variacao_limpo = padronizar_texto(dados_var.get('nome_variacao', 'SKU'))
                evidencia_limpa = padronizar_texto(leitura_evidencia)

                with st.container(border=True):
                    st.markdown(f"### {rotulo_acao(acao_var)} · {nome_variacao_limpo}")
                    st.caption(f"O que muda: {efeito_acao} {orientacao_acao}")
                    atual, proposto, decisao = st.columns(3, vertical_alignment="top")

                    with atual:
                        st.markdown("**Hoje**")
                        st.metric("Preço atual", f"R$ {preco_atual:.2f}")
                        st.caption(f"Vendas observadas: {int(dados_var.get('vendas_7d_reais', 0) or 0)} un. em 7 dias")
                        st.caption(f"Resultado operacional: R$ {float(dados_var.get('lucro_liquido_real_7d', 0) or 0):.2f}")

                    with proposto:
                        st.markdown("**Após a ação**")
                        if acao_var in {"AUMENTAR_PRECO", "REDUZIR_PRECO", "CRIAR_PROMOCAO"}:
                            delta_pct = ((novo_preco - preco_atual) / preco_atual * 100) if preco_atual else 0
                            st.metric("Preço proposto", f"R$ {novo_preco:.2f}", delta=f"{delta_pct:+.1f}%")
                        else:
                            st.metric("Preço", "Sem alteração direta")
                        faixa_min, faixa_max = intervalo_demanda_exploratorio(dados_var, float(analise_var.get('previsao_vendas_7d', 0) or 0))
                        st.caption(f"Demanda exploratória: {faixa_min}–{faixa_max} un. / 7 dias")
                        st.caption(f"Resultado projetado: R$ {float(analise_var.get('previsao_lucro_7d', 0) or 0):.2f}")

                    with decisao:
                        st.markdown("**Antes de decidir**")
                        st.caption(f"Evidência: **{confianca}** — {evidencia_limpa}")
                        st.caption("A projeção é uma hipótese. Confira a justificativa e a consequência abaixo antes de confirmar.")

                    with st.expander("Plano por horizonte: 7 dias e 30 dias"):
                        plano_7d, plano_30d = st.columns(2)
                        with plano_7d:
                            st.markdown("**Curto prazo · 7 dias**")
                            for passo in analise_var.get("plano_curto_prazo_7d", []):
                                st.write(f"• {padronizar_texto(passo)}")
                            st.caption(f"Cenário: {int(analise_var.get('previsao_vendas_7d', 0) or 0)} un. | R$ {float(analise_var.get('previsao_lucro_7d', 0) or 0):.2f}")

                        with plano_30d:
                            st.markdown("**Longo prazo · 30 dias**")
                            for passo in analise_var.get("plano_longo_prazo_30d", []):
                                st.write(f"• {padronizar_texto(passo)}")
                            st.caption(f"Cenário: {int(analise_var.get('previsao_vendas_30d', 0) or 0)} un. | R$ {float(analise_var.get('previsao_lucro_30d', 0) or 0):.2f}")
                        st.info("O plano de 30 dias é estratégico e não dispara nenhuma alteração automática.")

                    st.divider()
                    col_info, col_btn = st.columns([6, 4], vertical_alignment="center")

                    with col_info:
                        if confianca == "Baixa":
                            st.warning(f"Evidência baixa — não automatize sem teste controlado. {evidencia_limpa}")
                        else:
                            st.caption(f"Evidência {confianca.lower()}: {evidencia_limpa}")
                        st.markdown(f"**SKU:** `{nome_variacao_limpo}`")
                        st.caption(f"**Ação Definida:** {acao_var}")
                        if modo_execucao == "RECOMENDAR":
                            st.info("📌 Alteração Manual Necessária no Seller Center", icon="ℹ️")

                    with col_btn:
                        # 1. VERIFICAÇÃO DE ESTADO LOCAL (resistente ao F5)
                        status_local = analise_var.get("status_api_execucao")

                        if status_local == "SUCESSO":
                            st.success("✅ Confirmado ativo na Shopee", icon="🟢")
                            col_done, col_reverify = st.columns([3, 1])
                            with col_done:
                                st.button("Ação Concluída", key=f"done_{dados_var['model_id']}", disabled=True, use_container_width=True)
                            reverify_key = f"reverify_open_{dados_var['model_id']}"

                            with col_reverify:
                                if st.button("🔄", key=f"reverify_{dados_var['model_id']}", help="Reverificar na Shopee", use_container_width=True):
                                    st.session_state[reverify_key] = True
                                    st.rerun()

                            if st.session_state.get(reverify_key, False):
                                discount_id = analise_var.get("discount_id_shopee")

                                # IDs legados podem ser texto (bug antigo gravava a mensagem
                                # de sucesso do combo aqui) — sem ID numérico não há auto-check.
                                if not discount_id or not str(discount_id).isdigit():
                                    st.warning("Este item foi marcado como concluído antes da verificação automática existir. "
                                                "Confira manualmente no Seller Center. Se não estiver lá, use 'Liberar mesmo assim' abaixo.")
                                    if st.button("Liberar para nova tentativa", key=f"forcerelease_{dados_var['model_id']}"):
                                        analise_var["status_api_execucao"] = None
                                        st.session_state[reverify_key] = False
                                        salvar_cache_auditoria()
                                        st.rerun()
                                else:
                                    status_api, detalhe = verificar_status_promocao(discount_id)
                                    if status_api in ("ongoing", "upcoming"):
                                        st.toast(f"Confirmado: {detalhe}", icon="✅")
                                    elif status_api == "rejeitado":
                                        analise_var["status_api_execucao"] = None
                                        analise_var.pop("discount_id_shopee", None)
                                        salvar_cache_auditoria()
                                        st.toast("Não estava realmente ativo — liberado para nova tentativa.", icon="🔓")
                                    else:
                                        st.toast(f"Status ainda incerto ({status_api}). Tente de novo em instantes.", icon="❓")
                                    st.session_state[reverify_key] = False
                                    st.rerun()

                        elif status_local == "PENDENTE_VERIFICACAO":
                            st.warning("⏳ Enviado à Shopee, aguardando confirmação real", icon="🟡")
                            if st.button("Verificar status real", key=f"check_{dados_var['model_id']}", use_container_width=True):
                                discount_id = analise_var.get("discount_id_shopee")
                                if not discount_id or not str(discount_id).isdigit():
                                    # Registro legado (combo antigo gravava texto aqui): a API
                                    # já tinha aceitado o envio — libera o card e orienta.
                                    analise_var["status_api_execucao"] = "SUCESSO"
                                    salvar_cache_auditoria()
                                    st.toast("Envio já confirmado pela API; confira o combo no Seller Center.", icon="✅")
                                    st.rerun()
                                status_api, detalhe = verificar_status_promocao(discount_id)

                                if status_api in ("ongoing", "upcoming"):
                                    analise_var["status_api_execucao"] = "SUCESSO"
                                elif status_api == "rejeitado":
                                    analise_var["status_api_execucao"] = "FALHOU"
                                # se vier "desconhecido", mantém PENDENTE_VERIFICACAO pra tentar de novo depois

                                salvar_cache_auditoria()

                                st.toast(f"Status: {status_api} — {detalhe}", icon="🔎")
                                st.rerun()

                        elif status_local == "FALHOU":
                            st.error("❌ A Shopee rejeitou esta promoção", icon="🔴")
                            if st.button("Tentar novamente", key=f"retry_{dados_var['model_id']}", use_container_width=True):
                                analise_var["status_api_execucao"] = None
                                st.rerun()

                        else:
                            # 3. FLUXO NORMAL DE VALIDAÇÃO E EXECUÇÃO
                            valido, motivo = validar_sugestao_ia(dados_var, analise_var)
                            if confianca == "Baixa" and modo_execucao == "EXECUTAR":
                                valido = False
                                motivo = "Base histórica insuficiente para execução automática. Valide a hipótese manualmente ou reúna mais dados."

                            if not valido:
                                st.error(f"Bloqueado: {motivo}")

                            elif modo_execucao == "EXECUTAR":
                                st.caption("Confirmar envia esta alteração para a Shopee. Ela fica registrada no histórico de ações.")
                                txt_btn = "Confirmar promoção" if acao_var == "CRIAR_PROMOCAO" else "Confirmar criação do combo" if acao_var == "CRIAR_COMBO" else "Confirmar alteração de preço"

                                if st.button(txt_btn, key=f"exec_{dados_var['model_id']}", use_container_width=True, type="primary"):
                                    with st.spinner("Sincronizando com a Shopee em tempo real..."):

                                        # 4. DISPARO DA API (vinculando à execução analítica de origem)
                                        sucesso, msg = processar_acao_api(
                                            acao_var, dados_var, analise_var, novo_preco,
                                            id_execucao_origem=st.session_state.get("id_execucao_analitica"),
                                        )

                                        if sucesso:
                                            # 5. MUTAÇÃO DO ESTADO NA MEMÓRIA RAM
                                            if acao_var == "CRIAR_PROMOCAO":
                                                # Assíncrona na Shopee — fica pendente até verificarmos de fato
                                                # (msg aqui é o discount_id numérico)
                                                analise_var["status_api_execucao"] = "PENDENTE_VERIFICACAO"
                                                analise_var["discount_id_shopee"] = msg
                                            elif acao_var == "CRIAR_COMBO":
                                                # O bundle_deal é confirmado sincronicamente pela API
                                                # (add + attach validados, com failure_list checada);
                                                # verificar via get_discount era um bug — o ID não é
                                                # de desconto e o card ficava preso em "pendente".
                                                analise_var["status_api_execucao"] = "SUCESSO"
                                                analise_var["bundle_id_shopee"] = msg
                                            else:
                                                # Alteração de preço é síncrona — a Shopee confirma na hora
                                                analise_var["status_api_execucao"] = "SUCESSO"

                                            # 6. PERSISTÊNCIA FÍSICA NO DISCO (à prova de Refresh/F5)
                                            salvar_cache_auditoria()

                                            st.toast(f"Sincronização confirmada: {msg}", icon="✅")
                                            st.rerun()
                                        else:
                                            st.error(f"Falha na validação com a Shopee: {msg}")

    if sem_acoes:
        st.success("✅ O Conselho determinou que a estratégia atual está perfeita. Nenhuma intervenção de API é necessária hoje.")

# ==============================================================================
# ABA 3: ELASTICIDADE E PREVISÕES
# ==============================================================================
with aba_previsao:
    st.info("Previsões de 7 dias são cenários operacionais, não previsões estatísticas calibradas. Quando a evidência for baixa, use-as para priorizar investigação ou um teste pequeno — nunca como base única para alterar preço ou orçamento.")
    st.subheader("🧠 Elasticidade e Projeção de Demanda (7d)")
    st.caption("Visão preditiva do impacto do preço no volume de vendas baseado em dados históricos.")

    tabela_exec = []
    for a in analises:
        dados = a.get("dados_atuais", {})
        if not dados: continue
        tabela_exec.append({
            "Produto": dados.get("nome_produto", ""),
            "Variação": dados.get("nome_variacao", ""),
            "Ação Alvo": a.get("tipo_acao", "MANTER"),
            "Elasticidade": a.get("elasticidade_preco_volume", dados.get("elasticidade_preco_volume", 0)),
            "Previsão Vendas (7d)": a.get("previsao_vendas_7d", dados.get("previsao_vendas_7d", 0)),
            "Previsão Lucro (7d)": a.get("previsao_lucro_7d", dados.get("previsao_lucro_7d", 0)),
            "Previsão Vendas (30d)": a.get("previsao_vendas_30d", dados.get("previsao_vendas_30d", 0)),
            "Previsão Lucro (30d)": a.get("previsao_lucro_30d", dados.get("previsao_lucro_30d", 0)),
            "Margem un. (%)": dados.get("FINANCEIRO_margem_unitaria_perc"),
            "ACOS 7d (%)": dados.get("ADS_acos_medio") if float(dados.get("ADS_gasto_7d", 0) or 0) > 0 else None,
            "Evidência": classificar_confianca_evidencia(dados)[0],
            "Vendas observadas (30d)": dados.get("vendas_30d_macro", 0),
            "Cluster": a.get("cluster_mercado", dados.get("cluster_mercado", "Estável")),
        })

    if tabela_exec:
        df_pred = pd.DataFrame(tabela_exec).sort_values(["Previsão Lucro (30d)", "Previsão Lucro (7d)"], ascending=False)
        st.dataframe(
            df_pred,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Previsão Vendas (7d)": st.column_config.NumberColumn(format="%d un."),
                "Previsão Lucro (7d)": st.column_config.NumberColumn(format="R$ %.2f"),
                "Previsão Vendas (30d)": st.column_config.NumberColumn(format="%d un."),
                "Previsão Lucro (30d)": st.column_config.NumberColumn(format="R$ %.2f"),
                "Margem un. (%)": st.column_config.NumberColumn(format="%.0f%%", help="Margem unitária em % do preço = ACOS de equilíbrio para ads."),
                "ACOS 7d (%)": st.column_config.NumberColumn(format="%.0f%%", help="Só exibido quando houve gasto em ads no período. Compare com a margem unitária."),
            }
        )
        st.caption("Regra de bolso: ads é rentável enquanto o ACOS ficar abaixo da margem unitária em % do preço — esse é o ponto de equilíbrio de cada SKU.")

# ==============================================================================
# ABA 4: DOSSIÊS — correlações medidas, alavancas de crescimento e pareceres
# ==============================================================================
with aba_dossies:
    st.markdown("### Transparência da análise")
    data_cache = datetime.fromtimestamp(config.CACHE_AUDITORIA.stat().st_mtime).strftime('%d/%m/%Y %H:%M') if config.CACHE_AUDITORIA.exists() else 'não disponível'
    nota(
        f"{data_cache}. A camada determinística calcula vendas, custos de fabricação, ads, "
        "tráfego, carrinho, cancelamentos, cobertura de material e as correlações profundas "
        "(cesta de co-compra, dia da semana, geografia, views da API, margem unitária e curva "
        "ABC). O modelo IA recebe esse recorte e devolve recomendações textuais; ele não "
        "acessa dados adicionais nem valida causalidade.",
        titulo="Última auditoria em cache",
    )
    with st.expander("Ver critérios e limitações metodológicas"):
        st.markdown("""
        - O período operacional principal é de **7 dias**; 30 dias entram como contexto de demanda e tráfego.
        - A elasticidade só é interpretável se houve mudança material de preço e vendas suficientes. Sem isso, correlação não prova que o preço causou a variação de volume.
        - Tráfego e ads são dados no nível do anúncio/produto e são rateados entre variações (metade igualitário, metade proporcional às vendas de 30 dias); use a leitura por SKU como sinal, não como atribuição causal definitiva.
        - O lucro do escrow é rateado por participação de valor de cada item dentro do pedido.
        - **Margem unitária** = preço − taxa Shopee − fabricação. Em % do preço, ela é o **ACOS de equilíbrio**: campanha com ACOS acima dela consome toda a margem da venda.
        - **Cesta de co-compra** (180 dias), **melhor dia da semana** (90 dias) e **UF dominante** (90 dias) são correlações medidas nos pedidos reais; com amostra pequena, trate como indício.
        - **Views e curtidas da API** vêm dos snapshots diários da sincronização de saúde da conta; o delta de 7 dias só aparece com 2+ snapshots na janela.
        - **Curva ABC** classifica cada SKU pela contribuição ao lucro de 30 dias da loja (A ≈ 80% do resultado).
        - Resultado operacional não inclui todos os custos contábeis (por exemplo, mão de obra, impostos fora do repasse e frete, se não estiverem na origem).
        - Recomendações com baixa evidência ficam bloqueadas de execução automática nesta página.
        """)

    # ── Alavancas de crescimento (determinísticas, custo zero de IA) ──────────
    st.markdown("### 🚀 Alavancas de crescimento — sem custo de IA")
    st.caption(
        "Cada alavanca nasce de uma correlação medida no seu próprio dado (cesta de co-compra, "
        "dia da semana, ACOS × margem, estoque do anúncio, participação da variação, geografia). "
        "Nada aqui consome tokens de IA."
    )
    alavancas_por_produto = {}
    chaves_alavancas = set()
    for analise_alav in analises:
        dados_alav = analise_alav.get("dados_atuais", {})
        if not dados_alav:
            continue
        for alavanca in sugerir_alavancas_vendas(dados_alav):
            chave = (
                (dados_alav.get("item_id"), alavanca["titulo"])
                if alavanca["nivel"] == "produto"
                else (dados_alav.get("model_id"), alavanca["titulo"])
            )
            if chave in chaves_alavancas:
                continue
            chaves_alavancas.add(chave)
            registro = dict(alavanca)
            if alavanca["nivel"] == "variacao":
                registro["contexto"] = padronizar_texto(dados_alav.get("nome_variacao", ""))
            alavancas_por_produto.setdefault(
                padronizar_texto(dados_alav.get("nome_produto", "Produto")), []
            ).append(registro)

    if not alavancas_por_produto:
        st.success("Nenhuma alavanca óbvia pendente nos SKUs filtrados — a operação já aproveita o que os dados mostram.")
    else:
        for nome_prod_alav, alavancas_prod in alavancas_por_produto.items():
            with st.container(border=True):
                st.markdown(f"**{nome_prod_alav}**")
                for alavanca in alavancas_prod:
                    contexto = f" · `{alavanca['contexto']}`" if alavanca.get("contexto") else ""
                    st.markdown(f"{alavanca['icone']} **{alavanca['titulo']}**{contexto} — {alavanca['detalhe']}")

    st.divider()
    st.markdown("### 🎯 Ranking de Potencial de Margem")
    st.caption("Fórmula: Lucro / Gasto Ads + Fator Volume - Fator Cancelamento")

    ranking = df_analises.copy()
    ranking['potencial_margem'] = (
        ranking.get('lucro_liquido_real_7d', 0) / (ranking.get('ADS_gasto_7d', 0) + 1)
        + ranking.get('vendas_7d_reais', 0) * 0.2
        - ranking.get('taxa_cancelamento_7d_perc', 0) * 0.5
    )
    ranking_top = ranking.sort_values('potencial_margem', ascending=False).head(15)

    if not ranking_top.empty:
        st.dataframe(
            ranking_top[['nome_produto', 'nome_variacao', 'vendas_7d_reais', 'lucro_liquido_real_7d', 'ADS_gasto_7d', 'potencial_margem']],
            use_container_width=True,
            hide_index=True,
            column_config={
                "nome_produto": "Produto",
                "nome_variacao": "Variação",
                "vendas_7d_reais": "Vendas (7d)",
                "lucro_liquido_real_7d": st.column_config.NumberColumn("Margem Real", format="R$ %.2f"),
                "ADS_gasto_7d": st.column_config.NumberColumn("Gasto Ads", format="R$ %.2f"),
                "potencial_margem": st.column_config.NumberColumn("Score de Potencial", format="%.2f")
            }
        )

    st.divider()
    st.markdown("### 📖 Dossiês e Pareceres de Diretoria")
    st.caption(
        "O raio-X de cada anúncio: correlações medidas, funil de 7 dias com escudo de nulos e a "
        "defesa argumentativa do Conselho (CFO, CMO, COO) por variação."
    )

    for iid, p in produtos_agrupados.items():
        variacoes_produto = p["variacoes"]
        dados_base = variacoes_produto[0].get("dados_atuais", {})
        classes_abc = {v.get("dados_atuais", {}).get("PORTFOLIO_curva_abc") for v in variacoes_produto}
        classe_abc = next((c for c in ("A", "B", "C") if c in classes_abc), None)
        rotulo_abc = f" · Curva {classe_abc}" if classe_abc else ""

        with st.expander(f"Ler dossiê: {padronizar_texto(p['nome_produto'])} · {len(variacoes_produto)} SKU(s){rotulo_abc}"):
            # Perfil do anúncio: imagem + correlações medidas
            if dados_base.get("imagem_url"):
                col_img, col_perfil = st.columns([1, 5], vertical_alignment="center")
                col_img.image(dados_base["imagem_url"], width=110)
            else:
                col_perfil = st.container()

            correlacoes = []
            melhor_dia_prod = dados_base.get("VENDAS_melhor_dia_semana")
            if melhor_dia_prod:
                share_dia_prod = _float_ou_none(dados_base.get("VENDAS_share_melhor_dia_perc"))
                sufixo_dia = f" ({share_dia_prod:.0f}% das vendas de 90d)" if share_dia_prod else ""
                correlacoes.append(f"📅 Melhor dia: **{melhor_dia_prod}**{sufixo_dia}")
            uf_prod = dados_base.get("GEO_uf_top")
            if uf_prod:
                share_uf_prod = _float_ou_none(dados_base.get("GEO_uf_top_share_perc")) or 0
                base_uf_prod = int(dados_base.get("GEO_pedidos_com_uf_90d", 0) or 0)
                correlacoes.append(f"🗺️ UF dominante: **{uf_prod}** ({share_uf_prod:.0f}% de {base_uf_prod} pedidos)")
            parceiro_prod = dados_base.get("CESTA_parceiro_top")
            conjuntos_prod = int(dados_base.get("CESTA_pedidos_conjuntos_180d", 0) or 0)
            if parceiro_prod and conjuntos_prod >= 1:
                correlacoes.append(f"🧺 Sai junto com: **{padronizar_texto(parceiro_prod)}** ({conjuntos_prod}× em 180d)")
            api_views_prod = dados_base.get("API_views_7d")
            if api_views_prod is not None:
                curtidas_prod = dados_base.get("API_curtidas_7d")
                sufixo_curtidas = f" · ❤️ +{int(curtidas_prod)}" if curtidas_prod else ""
                correlacoes.append(f"👁️ Views pela API (7d): **{_fmt_qtd(api_views_prod)}**{sufixo_curtidas}")
            recompra_prod = _float_ou_none(dados_base.get("POSVENDA_recompra_perc_180d"))
            if recompra_prod is not None:
                base_rec_prod = int(dados_base.get("POSVENDA_pedidos_identificados_180d", 0) or 0)
                correlacoes.append(f"🔁 Recompra: **{recompra_prod:.0f}%** dos {base_rec_prod} pedidos (180d) de clientes que voltaram")
            preparo_prod = _float_ou_none(dados_base.get("POSVENDA_preparo_mediano_horas"))
            if preparo_prod is not None:
                atraso_prod = _float_ou_none(dados_base.get("POSVENDA_preparo_atrasado_perc"))
                sufixo_atraso = f" · **{atraso_prod:.0f}%** fora do prazo" if atraso_prod is not None else ""
                correlacoes.append(f"🕒 Preparo mediano: **{preparo_prod:.0f}h**{sufixo_atraso}")
            entrega_prod = _float_ou_none(dados_base.get("POSVENDA_entrega_mediana_dias"))
            if entrega_prod is not None:
                correlacoes.append(f"🚚 Entrega mediana: **{entrega_prod:.0f} dia(s)** após a coleta")
            devolucoes_prod = int(dados_base.get("POSVENDA_devolucoes_90d", 0) or 0)
            if devolucoes_prod:
                motivo_prod = dados_base.get("POSVENDA_devolucao_motivo")
                sufixo_motivo = f" ({padronizar_texto(str(motivo_prod))})" if motivo_prod else ""
                correlacoes.append(f"↩️ Devoluções (90d): **{devolucoes_prod}**{sufixo_motivo}")
            promo_prod = dados_base.get("PROMO_ativa_tipo")
            if promo_prod:
                fim_promo = str(dados_base.get("PROMO_ativa_fim") or "")[:10]
                sufixo_fim = f" até **{fim_promo[8:10]}/{fim_promo[5:7]}**" if len(fim_promo) == 10 else ""
                correlacoes.append(f"🏷️ **Em promoção** ({promo_prod}){sufixo_fim} — elasticidade e preço do período refletem a promoção")
            estrelas_prod = _float_ou_none(dados_base.get("REPUTACAO_estrelas")) or 0
            favoritos_prod = int(dados_base.get("REPUTACAO_curtidas_favoritos", 0) or 0)
            correlacoes.append(f"⭐ {estrelas_prod:.1f} estrelas · ❤️ {favoritos_prod} favoritos")
            col_perfil.markdown("  \n".join(correlacoes))

            # Funil de 7 dias do anúncio inteiro (rateios somados = totais exatos)
            impressoes_item = _soma_com_escudo(variacoes_produto, "TRAFEGO_ORG_impressoes_7d")
            impressoes_ads_item = _soma_com_escudo(variacoes_produto, "ADS_impressoes_7d")
            if impressoes_item is not None or impressoes_ads_item is not None:
                impressoes_totais = (impressoes_item or 0) + (impressoes_ads_item or 0)
            else:
                impressoes_totais = None
            cliques_item = _soma_com_escudo(variacoes_produto, "TRAFEGO_ORG_cliques_7d")
            cliques_ads_item = _soma_com_escudo(variacoes_produto, "ADS_cliques_7d")
            if cliques_item is not None or cliques_ads_item is not None:
                cliques_totais = (cliques_item or 0) + (cliques_ads_item or 0)
            else:
                cliques_totais = None
            visitas_item = _soma_com_escudo(variacoes_produto, "TRAFEGO_visitas_7d") or 0
            carrinhos_item = _soma_com_escudo(variacoes_produto, "TRAFEGO_adicoes_carrinho_7d") or 0
            vendas_item = _soma_com_escudo(variacoes_produto, "vendas_7d_reais") or 0

            st.markdown("**Funil de 7 dias — anúncio inteiro**")
            f1, f2, f3, f4, f5 = st.columns(5)
            f1.metric("Impressões", _fmt_qtd(impressoes_totais), help="Orgânico + ads. '—' significa dado não coletado (não é zero).")
            ctr_funil = (
                f"CTR {cliques_totais / impressoes_totais * 100:.1f}%"
                if cliques_totais is not None and impressoes_totais else None
            )
            f2.metric("Cliques", _fmt_qtd(cliques_totais), delta=ctr_funil, delta_color="off")
            f3.metric("Visitas", _fmt_qtd(visitas_item))
            taxa_carrinho = f"{carrinhos_item / visitas_item * 100:.0f}% das visitas" if visitas_item else None
            f4.metric("Carrinhos", _fmt_qtd(carrinhos_item), delta=taxa_carrinho, delta_color="off")
            conversao_funil = f"conversão {vendas_item / visitas_item * 100:.1f}%" if visitas_item else None
            f5.metric("Vendas", _fmt_qtd(vendas_item), delta=conversao_funil, delta_color="off")

            visitas_30d_item = _soma_com_escudo(variacoes_produto, "TRAFEGO_visitas_30d") or 0
            carrinhos_30d_item = _soma_com_escudo(variacoes_produto, "TRAFEGO_adicoes_carrinho_30d") or 0
            vendas_30d_item_funil = _soma_com_escudo(variacoes_produto, "vendas_30d_reais") or 0
            conversao_30d_funil = f" · conversão {vendas_30d_item_funil / visitas_30d_item * 100:.1f}%" if visitas_30d_item else ""
            st.caption(
                f"Contexto de 30 dias: {_fmt_qtd(visitas_30d_item)} visitas · {_fmt_qtd(carrinhos_30d_item)} carrinhos · "
                f"{_fmt_qtd(vendas_30d_item_funil)} vendas{conversao_30d_funil}"
            )

            st.divider()
            st.markdown("**Pareceres por variação**")
            if len(variacoes_produto) == 1:
                _render_parecer_variacao(variacoes_produto[0])
            else:
                nomes_tabs = []
                contagem_nomes = {}
                for v in variacoes_produto:
                    nome_v = padronizar_texto(v.get("dados_atuais", {}).get("nome_variacao", "SKU")) or "SKU"
                    contagem_nomes[nome_v] = contagem_nomes.get(nome_v, 0) + 1
                    nomes_tabs.append(nome_v if contagem_nomes[nome_v] == 1 else f"{nome_v} ({contagem_nomes[nome_v]})")
                if len(variacoes_produto) > 8:
                    indice_var = st.selectbox(
                        "Escolher variação", range(len(variacoes_produto)),
                        format_func=lambda i: nomes_tabs[i], key=f"dossie_var_{iid}",
                    )
                    _render_parecer_variacao(variacoes_produto[indice_var])
                else:
                    for tab_var, analise_var_dossie in zip(st.tabs(nomes_tabs), variacoes_produto):
                        with tab_var:
                            _render_parecer_variacao(analise_var_dossie)
