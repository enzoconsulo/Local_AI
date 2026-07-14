"""
pages/3_🧠_Cerebro_IA.py
========================
Conselho de Administração IA (CFO, CMO, COO) + Atuador Shopee.

Esta página contém APENAS interface. Toda a lógica vive no pacote `cerebro/`:
extração (dossie), heurísticas determinísticas, memória analítica, motor
OpenAI, atuador e orquestração. Consulte cerebro/__init__.py para o mapa.
"""

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from utils.padronizar_texto import padronizar_texto
from cerebro import config, orquestrador
from cerebro.atuador import processar_acao_api, verificar_status_promocao
from cerebro.config import classificar_modo_execucao, explicar_acao, rotulo_acao
from cerebro.heuristicas import (
    classificar_confianca_evidencia,
    gerar_alertas_criticos,
    intervalo_demanda_exploratorio,
)
from cerebro.motor_ia import validar_sugestao_ia

st.set_page_config(
    page_title="Cérebro Analítico & Atuador",
    page_icon="🧠",
    layout="wide"
)


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


# ══════════════════════════════════════════════════════════════════════════════
# ESTRUTURA PRINCIPAL DA TELA
# ══════════════════════════════════════════════════════════════════════════════

st.title("🧠 Conselho C-Level & Atuador IA")
st.markdown("Auditoria profunda de **Finanças, Marketing e Fábrica** com predição de cenários e gatilhos de Notificação (Push) na Shopee.")

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
    st.caption("A análise de 7 dias é operacional e deve ser usada no dia a dia. A análise de 30 dias é estratégica, mais completa e indicada na primeira execução ou após longo período sem revisão.")
    botao_7d, botao_30d = st.columns(2)
    executar_7d = botao_7d.button("Atualizar análise operacional · 7 dias", type="primary", use_container_width=True, help="Envia somente os sinais recentes ao modelo. É o fluxo recomendado para uso recorrente.")
    executar_30d = botao_30d.button("Executar diagnóstico estratégico · 30 dias", use_container_width=True, help="Envia o dossiê mensal completo. Use na primeira execução e em revisões estratégicas.")

    horizonte_escolhido = "7d" if executar_7d else "30d" if executar_30d else None
    if horizonte_escolhido:
        titulo = "análise operacional de 7 dias" if horizonte_escolhido == "7d" else "diagnóstico estratégico de 30 dias"
        with st.status(f"Iniciando {titulo}...", expanded=True) as status_boot:
            resultados_ia = orquestrador.executar_auditoria_por_horizonte(horizonte_escolhido, status_boot)
            st.session_state.analises_preditivas = resultados_ia
            st.session_state.horizonte_auditoria = horizonte_escolhido
            status_boot.update(label=f"{titulo.capitalize()} concluído!", state="complete", expanded=False)
        st.rerun()

analises = st.session_state.analises_preditivas
if not analises:
    st.warning("Ainda não há uma auditoria carregada. Use “Executar Auditoria Profunda” acima para criar o primeiro diagnóstico.")
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
    st.info("Nenhum SKU corresponde aos filtros atuais. Ajuste os filtros na barra lateral.")
    st.stop()

st.markdown("""
<style>
    .stApp {font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;}
    .block-container {max-width: 1440px; padding-top: 2rem; padding-bottom: 3rem;}
    div[data-testid="stTabs"] button {font-size: .95rem; font-weight: 600; padding: .75rem 1rem;}
    div[data-testid="stTabs"] button[aria-selected="true"] {color: #5b8def;}
    div[data-testid="stButton"] > button {border-radius: 10px; min-height: 2.75rem; font-weight: 600;}
    div[data-testid="stExpander"] {border-radius: 12px; border-color: rgba(128, 145, 180, .35);}
    div[data-testid="stMetric"] {background: linear-gradient(135deg, #101b35, #16254a); border: 1px solid #2b4273; border-radius: 12px; padding: 14px;}
    div[data-testid="stMetricLabel"] {color: #b9c7e6;}
    div[data-testid="stMetricValue"] {color: #f7f9ff;}
    .ia-note {padding: .85rem 1rem; border-left: 4px solid #5b8def; background: #101b35; border-radius: 8px; margin: .4rem 0 1rem;}
    .ia-label {font-size: .78rem; letter-spacing: .04em; color: #aebee3; text-transform: uppercase;}
</style>
""", unsafe_allow_html=True)

# ─── Organização em 4 Abas Ergonômicas ────────────────────────────────────────
aba_dashboard, aba_atuador, aba_previsao, aba_dossies = st.tabs([
    "Resumo",
    "Alterações recomendadas",
    "Cenários e previsões",
    "Pareceres e método"
])

# ==============================================================================
# ABA 1: VISÃO EXECUTIVA (KPIs, Categorias e Alertas)
# ==============================================================================
with aba_dashboard:
    st.markdown('<div class="ia-note"><span class="ia-label">Leitura responsável</span><br>Fatos observados (7 dias) são exibidos com contexto de 30 dias. A IA formula hipóteses de ação; a classificação de evidência indica quando executar, testar em pequena escala ou somente monitorar.</div>', unsafe_allow_html=True)

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
        lambda row: f"{float(row.get('elasticidade_preco_volume', 0)):.2f}" if abs(float(row.get('preco_tendencia_7d_perc', 0))) >= 0.5 and float(row.get('vendas_30d_macro', 0)) >= 5 else "Não identificável",
        axis=1
    )
    fila_decisao = fila_decisao.sort_values(['score_urgencia', 'lucro_liquido_real_7d'], ascending=[False, True])
    colunas_fila = ['nome_produto', 'nome_variacao', 'ação', 'confianca', 'score_urgencia', 'lucro_liquido_real_7d', 'faixa_demanda_7d', 'elasticidade_legivel', 'leitura_evidencia']
    st.dataframe(
        fila_decisao[colunas_fila], use_container_width=True, hide_index=True, height=280,
        column_config={
            'nome_produto': 'Produto', 'nome_variacao': 'SKU', 'ação': 'Próxima ação',
            'confianca': 'Evidência', 'score_urgencia': st.column_config.ProgressColumn('Prioridade', min_value=0, max_value=100, format='%d/100'),
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
    st.markdown('<div class="ia-note"><span class="ia-label">Fluxo de confirmação</span><br><b>1. Compare</b> o estado atual com o proposto. &nbsp; <b>2. Leia</b> a força da evidência e a consequência. &nbsp; <b>3. Confirme</b> somente quando a alteração estiver clara. Nenhum botão é executado sem clique explícito.</div>', unsafe_allow_html=True)
    st.info("Fluxo recomendado: analise a recomendação, confira a variação do preço alvo e aprove a ação em 1-clique.")

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

                                if not discount_id:
                                    # Item marcado SUCESSO por execução antiga, sem discount_id salvo — não dá pra auto-checar
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
                                            if acao_var in ("CRIAR_PROMOCAO", "CRIAR_COMBO"):
                                                # Assíncrono na Shopee — fica pendente até verificarmos de fato
                                                analise_var["status_api_execucao"] = "PENDENTE_VERIFICACAO"
                                                analise_var["discount_id_shopee"] = msg
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
                "Previsão Lucro (30d)": st.column_config.NumberColumn(format="R$ %.2f")
            }
        )

# ==============================================================================
# ABA 4: DOSSIÊS E RANKINGS (Textos integrais da IA)
# ==============================================================================
with aba_dossies:
    st.markdown("### Transparência da análise")
    data_cache = datetime.fromtimestamp(config.CACHE_AUDITORIA.stat().st_mtime).strftime('%d/%m/%Y %H:%M') if config.CACHE_AUDITORIA.exists() else 'não disponível'
    st.markdown(f'<div class="ia-note"><span class="ia-label">Última auditoria em cache</span><br>{data_cache}. A camada determinística calcula vendas, custos de fabricação, ads, tráfego, carrinho, cancelamentos e cobertura de material. O modelo IA recebe esse recorte e devolve recomendações textuais; ele não acessa dados adicionais nem valida causalidade.</div>', unsafe_allow_html=True)
    with st.expander("Ver critérios e limitações metodológicas"):
        st.markdown("""
        - O período operacional principal é de **7 dias**; 30 dias entram como contexto de demanda e tráfego.
        - A elasticidade só é interpretável se houve mudança material de preço e vendas suficientes. Sem isso, correlação não prova que o preço causou a variação de volume.
        - Tráfego e ads são dados no nível do anúncio/produto e são rateados entre variações (metade igualitário, metade proporcional às vendas de 30 dias); use a leitura por SKU como sinal, não como atribuição causal definitiva.
        - O lucro do escrow é rateado por participação de valor de cada item dentro do pedido.
        - Resultado operacional não inclui todos os custos contábeis (por exemplo, mão de obra, impostos fora do repasse e frete, se não estiverem na origem).
        - Recomendações com baixa evidência ficam bloqueadas de execução automática nesta página.
        """)
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
    st.caption("Acesse a defesa argumentativa do Conselho C-Level (CFO, CMO, COO) gerada pela IA para cada produto.")

    for iid, p in produtos_agrupados.items():
        var_base = p["variacoes"][0]
        with st.expander(f"Ler Parecer: {p['nome_produto']}"):
            st.markdown(f"**Recomendação Executiva:** {var_base.get('recomendacao_executiva', 'N/A')}")

            c1, c2, c3 = st.columns(3)
            with c1: st.info(f"**💰 Parecer CFO (Finanças):**\n\n{var_base.get('relatorio_cfo_financas', 'N/A')}")
            with c2: st.success(f"**🎯 Parecer CMO (Marketing):**\n\n{var_base.get('relatorio_cmo_marketing', 'N/A')}")
            with c3: st.warning(f"**🏭 Parecer COO (Operações):**\n\n{var_base.get('relatorio_coo_operacoes', 'N/A')}")
