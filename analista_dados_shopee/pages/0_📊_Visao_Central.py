"""
pages/0_📊_Visao_Central.py
===========================
Centro de comando da loja: TODOS os dados importantes num lugar só, com o
plano de ação calculado 100% localmente (heurísticas determinísticas do
pacote cerebro/ — custo de IA externa: R$ 0,00). A OpenAI só é chamada na
página 3, quando você pedir o parecer completo.

Seções:
  1. Frescor dos dados + instruções exatas de onde exportar cada fonte
  2. KPIs macro da loja (7 dias vs 7 anteriores)
  3. Funil de conversão consolidado (onde o cliente desiste)
  4. Saúde da conta via API (o que decide seu alcance orgânico)
  5. Alcance grátis: Boost de produtos (5 itens / 4 horas, sem custo)
  6. Voucher de checkout contra o abandono de carrinho (v2.voucher)
  7. Radar por produto via API (views/curtidas sem planilha)
  8. Plano de ação determinístico com consequências e previsões
"""

import pandas as pd
import streamlit as st

from utils.db_pool import get_connection
from utils.shopee_core import (
    listar_boost_ativo,
    impulsionar_itens,
    criar_voucher_loja,
    listar_vouchers,
    encerrar_voucher,
)
from workers.sync_saude_conta import sincronizar_saude_conta, sincronizar_metricas_api_produtos
from cerebro import heuristicas
from cerebro.config import MigracaoPendenteError
from cerebro.dossie import gerar_dossie_produtos_com_memoria
from cerebro.atuador import salvar_log_acao

from utils.ui import aplicar_estilo, cabecalho, secao

st.set_page_config(page_title="Visão Central", page_icon="📊", layout="wide")
aplicar_estilo()
cabecalho(
    "📊", "Visão Central da Loja",
    "Análise profunda calculada no seu computador — zero tokens de IA nesta página. "
    "Para o parecer estratégico da OpenAI, use a página 🧠 Cérebro IA.",
)


# ══════════════════════════════════════════════════════════════════════════════
# CARREGADORES (cache curto: a página é re-executada a cada clique)
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=120, show_spinner=False)
def carregar_kpis_macro():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    SUM(metric_value) FILTER (WHERE metric_name = 'vendas_brl' AND data_registro >= CURRENT_DATE - 7)  AS receita_7d,
                    SUM(metric_value) FILTER (WHERE metric_name = 'vendas_brl' AND data_registro >= CURRENT_DATE - 14 AND data_registro < CURRENT_DATE - 7) AS receita_7d_ant,
                    SUM(metric_value) FILTER (WHERE metric_name = 'pedidos' AND data_registro >= CURRENT_DATE - 7)     AS pedidos_7d,
                    SUM(metric_value) FILTER (WHERE metric_name = 'pedidos' AND data_registro >= CURRENT_DATE - 14 AND data_registro < CURRENT_DATE - 7) AS pedidos_7d_ant,
                    SUM(metric_value) FILTER (WHERE metric_name = 'visitantes' AND data_registro >= CURRENT_DATE - 7)  AS visitantes_7d,
                    SUM(metric_value) FILTER (WHERE metric_name = 'visitantes' AND data_registro >= CURRENT_DATE - 14 AND data_registro < CURRENT_DATE - 7) AS visitantes_7d_ant,
                    AVG(metric_value) FILTER (WHERE metric_name LIKE 'taxa_de_convers%%' AND data_registro >= CURRENT_DATE - 7) AS conversao_7d,
                    AVG(metric_value) FILTER (WHERE metric_name LIKE 'taxa_de_convers%%' AND data_registro >= CURRENT_DATE - 14 AND data_registro < CURRENT_DATE - 7) AS conversao_7d_ant,
                    SUM(metric_value) FILTER (WHERE metric_name = 'vendas_canceladas' AND data_registro >= CURRENT_DATE - 7) AS canceladas_7d,
                    MAX(data_registro) FILTER (WHERE metric_name = 'vendas_brl') AS ultimo_dia
                FROM fato_visao_geral_loja
                WHERE fonte NOT LIKE 'API_%%';
            """)
            r = cur.fetchone()
    campos = ["receita_7d", "receita_7d_ant", "pedidos_7d", "pedidos_7d_ant", "visitantes_7d",
              "visitantes_7d_ant", "conversao_7d", "conversao_7d_ant", "canceladas_7d", "ultimo_dia"]
    return {c: (float(v) if v is not None and c != "ultimo_dia" else v) for c, v in zip(campos, r)}


@st.cache_data(ttl=120, show_spinner=False)
def carregar_funil(dias: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COALESCE(SUM(impressoes),0), COALESCE(SUM(cliques),0),
                       COALESCE(SUM(visitantes_unicos),0), COALESCE(SUM(adicoes_carrinho),0)
                FROM fato_trafego_diario WHERE data >= CURRENT_DATE - %s;
            """, (dias,))
            imp, cli, vis, car = cur.fetchone()
            cur.execute("""
                SELECT COALESCE(SUM(unidades_vendidas),0), COALESCE(SUM(pedidos),0)
                FROM vw_vendas_diarias_variacao WHERE data >= CURRENT_DATE - %s;
            """, (dias,))
            unidades, pedidos = cur.fetchone()
            cur.execute("""
                SELECT COALESCE(SUM(investimento),0), COALESCE(SUM(vendas_gmv),0),
                       COALESCE(SUM(impressoes),0), COALESCE(SUM(cliques),0)
                FROM fato_ads_performance_produto WHERE data_registro >= CURRENT_DATE - %s;
            """, (dias,))
            gasto, gmv, imp_ads, cli_ads = cur.fetchone()
    return {
        "impressoes": int(imp), "cliques": int(cli), "visitas": int(vis), "carrinhos": int(car),
        "unidades": int(unidades), "pedidos": int(pedidos),
        "ads_gasto": float(gasto), "ads_gmv": float(gmv),
        "ads_impressoes": int(imp_ads), "ads_cliques": int(cli_ads),
    }


@st.cache_data(ttl=120, show_spinner=False)
def carregar_frescor():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ON (modulo) modulo, data_execucao, data_fim_coleta, status, registros_afetados
                FROM sys_controle_sync
                ORDER BY modulo, data_execucao DESC;
            """)
            return cur.fetchall()


@st.cache_data(ttl=120, show_spinner=False)
def carregar_saude_historico():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT data_registro, metric_name, metric_value
                FROM fato_visao_geral_loja
                WHERE fonte = 'API_SAUDE_CONTA'
                ORDER BY data_registro DESC, metric_name
                LIMIT 200;
            """)
            return cur.fetchall()


@st.cache_data(ttl=120, show_spinner=False)
def carregar_radar_api():
    """Último snapshot de views/curtidas por item + delta vs snapshot anterior."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                WITH serie AS (
                    SELECT item_id, metric_name, data_registro, metric_value,
                           LAG(metric_value) OVER (PARTITION BY item_id, metric_name ORDER BY data_registro) AS anterior,
                           LAG(data_registro) OVER (PARTITION BY item_id, metric_name ORDER BY data_registro) AS data_anterior,
                           ROW_NUMBER() OVER (PARTITION BY item_id, metric_name ORDER BY data_registro DESC) AS rn
                    FROM fato_metricas_produto_importadas
                    WHERE fonte = 'API_EXTRA_INFO'
                ),
                ultimo AS (SELECT * FROM serie WHERE rn = 1)
                SELECT p.item_id, p.nome_atual,
                    MAX(u.metric_value) FILTER (WHERE u.metric_name = 'api_views_acumuladas')     AS views,
                    MAX(u.anterior)     FILTER (WHERE u.metric_name = 'api_views_acumuladas')     AS views_ant,
                    MAX(u.data_anterior) FILTER (WHERE u.metric_name = 'api_views_acumuladas')    AS data_ant,
                    MAX(u.metric_value) FILTER (WHERE u.metric_name = 'api_curtidas_acumuladas')  AS curtidas,
                    MAX(u.metric_value) FILTER (WHERE u.metric_name = 'api_vendas_acumuladas')    AS vendas_acum,
                    MAX(u.metric_value) FILTER (WHERE u.metric_name = 'api_avaliacoes_acumuladas') AS avaliacoes,
                    MAX(u.data_registro) AS data_snapshot
                FROM ultimo u JOIN dim_produtos p ON p.item_id = u.item_id
                GROUP BY p.item_id, p.nome_atual
                ORDER BY 3 DESC NULLS LAST;
            """)
            return cur.fetchall()


@st.cache_data(ttl=120, show_spinner=False)
def carregar_economia_real():
    """Números que são SEUS de verdade: cesta que o cliente paga (itens do
    pedido) e repasse líquido do escrow — nada de 'Vendas (BRL)' bruto da
    planilha, que embute taxas que você nunca recebe."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(DISTINCT p.order_sn)                                     AS pedidos_30d,
                    SUM(i.preco_praticado * i.quantidade)
                        / NULLIF(COUNT(DISTINCT p.order_sn), 0)                    AS cesta_media_cliente,
                    COUNT(DISTINCT r.order_sn)                                     AS pedidos_liquidados,
                    AVG(r.lucro_liquido_absoluto)                                  AS repasse_medio_pedido
                FROM fato_pedidos_venda p
                JOIN fato_itens_pedido i  ON i.order_sn = p.order_sn
                LEFT JOIN fato_repasse_escrow r ON r.order_sn = p.order_sn
                WHERE p.data_hora_criacao >= CURRENT_DATE - 30
                  AND p.status_pedido NOT IN ('CANCELLED','CANCELED','CANCELLED_BY_BUYER','IN_CANCEL');
            """)
            pedidos_30d, cesta, liquidados, repasse_medio = cur.fetchone()
    return {
        "pedidos_30d": int(pedidos_30d or 0),
        "cesta_media_cliente": float(cesta) if cesta is not None else None,
        "pedidos_liquidados": int(liquidados or 0),
        "repasse_medio_pedido": float(repasse_medio) if repasse_medio is not None else None,
    }


@st.cache_data(ttl=300, show_spinner=False)
def carregar_fotos():
    """Capa do anúncio (migração 15, populada pelo sync de catálogo)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT item_id, imagem_url FROM dim_produtos WHERE imagem_url IS NOT NULL")
            return dict(cur.fetchall())


@st.cache_data(ttl=300, show_spinner="Calculando dossiê local (sem IA externa)...")
def carregar_dossie():
    return gerar_dossie_produtos_com_memoria()


def _fmt_moeda(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ══════════════════════════════════════════════════════════════════════════════
# 1. FRESCOR DOS DADOS + INSTRUÇÕES DE IMPORTAÇÃO
# ══════════════════════════════════════════════════════════════════════════════

secao(1, "Saúde dos dados", "O que alimenta as análises — mantenha os semáforos verdes.")

ROTULOS_MODULOS = {
    "PEDIDOS": ("🛒 Pedidos + Lucro (API)", "Automático na página 2 — botão 'Iniciar Sincronização'"),
    "VISAO_GERAL": ("🏪 Visão Geral da Loja (planilha)", "Exportar a cada 7 dias"),
    "TRAFEGO_ORG": ("🌱 Tráfego Orgânico por produto (planilha)", "Exportar a cada 7 dias"),
    "ADS_AVANCADO": ("📢 Shopee Ads (planilha)", "Exportar a cada 7 dias, se investir em Ads"),
    "SAUDE_CONTA": ("❤️ Saúde da Conta (API)", "Botão nesta página — 1 clique"),
    "METRICAS_API_PRODUTOS": ("📡 Radar de produto (API)", "Botão nesta página — 1 clique"),
}

frescor = carregar_frescor()
if frescor:
    linhas = []
    for modulo, execucao, fim_coleta, status, registros in frescor:
        rotulo, cadencia = ROTULOS_MODULOS.get(modulo, (modulo, "—"))
        idade_dias = (pd.Timestamp.now() - pd.Timestamp(execucao)).days if execucao else None
        if idade_dias is None:
            semaforo = "⚪ nunca"
        elif idade_dias <= 2:
            semaforo = f"🟢 há {idade_dias}d"
        elif idade_dias <= 7:
            semaforo = f"🟡 há {idade_dias}d"
        else:
            semaforo = f"🔴 há {idade_dias}d"
        linhas.append({
            "Fonte": rotulo, "Última atualização": semaforo,
            "Cobertura até": fim_coleta.strftime("%d/%m/%Y") if fim_coleta else "—",
            "Registros": registros, "Como manter em dia": cadencia,
        })
    st.dataframe(pd.DataFrame(linhas), use_container_width=True, hide_index=True)
else:
    st.info("Nenhuma sincronização registrada ainda. Comece pela página 2 🔄.")

with st.expander("📚 Passo a passo EXATO de cada exportação (clique para abrir)"):
    st.markdown("""
| Fonte | Onde encontrar no Seller Center | Período recomendado | Onde subir |
|---|---|---|---|
| **🏪 Visão Geral** | [Dados → Painel](https://seller.shopee.com.br/datacenter/dashboard) → canto superior direito **Exportar** (arquivo `...shop-stats....xlsx`) | Últimos 30 dias | Página 2 → seção *Visão Geral* |
| **🌱 Tráfego Orgânico** | [Dados → Produtos → Performance](https://seller.shopee.com.br/datacenter/product/performance) → aba *Desempenho do Produto* → **Exportar** (arquivo `parentskudetail....xlsx`) | Mesmo período selecionado no filtro | Página 2 → seção *Tráfego* (informe o MESMO período do filtro) |
| **📢 Shopee Ads** | [Central de Anúncios](https://ads.shopee.com.br) → *Dados Gerais* → **Exportar** (+ o **GMV Max Detail**, se usar GMV Max; **não** suba o arquivo *Ad Group* — seria contado 2×) | 7 dias fechados | Página 2 → seção *Ads* |
| **🛒 Pedidos/Lucro, ❤️ Saúde, 📡 Radar** | Nada a exportar — vêm direto da **API oficial** | — | Botões (página 2 e esta página) |

**Regra de ouro do período:** sempre exporte e informe *períodos fechados e consistentes*
(ex.: sempre 7 dias, seg→dom). Períodos diferentes que se cruzam sobrescrevem o rateio
diário dos dias em comum — a página 2 avisa quando isso acontecer.
""")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# 2. KPIs MACRO
# ══════════════════════════════════════════════════════════════════════════════

secao(2, "Termômetro da loja", "Últimos 7 dias comparados com os 7 anteriores.")

kpi = carregar_kpis_macro()
if kpi["receita_7d"] is None and kpi["pedidos_7d"] is None:
    st.warning("Sem dados da planilha de Visão Geral ainda. Exporte-a (instruções acima) e suba na página 2.")
else:
    def _delta(atual, anterior):
        if not anterior:
            return None
        return f"{((atual or 0) - anterior) / anterior * 100:+.1f}%"

    economia = carregar_economia_real()
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("🛍️ Vendas BRUTAS", _fmt_moeda(kpi["receita_7d"] or 0), _delta(kpi["receita_7d"], kpi["receita_7d_ant"]))
    c1.caption("o que o CLIENTE pagou — não é o que você recebe")
    if economia["repasse_medio_pedido"] is not None:
        c2.metric("💵 Ganho líquido/pedido", _fmt_moeda(economia["repasse_medio_pedido"]))
        c2.caption(f"média REAL dos {economia['pedidos_liquidados']} pedidos já liquidados no escrow (30d)")
    else:
        c2.metric("💵 Ganho líquido/pedido", "—")
        c2.caption("nenhum escrow liquidado ainda — sincronize pedidos na página 2")
    c3.metric("📦 Pedidos", int(kpi["pedidos_7d"] or 0), _delta(kpi["pedidos_7d"], kpi["pedidos_7d_ant"]))
    c4.metric("👀 Visitantes", int(kpi["visitantes_7d"] or 0), _delta(kpi["visitantes_7d"], kpi["visitantes_7d_ant"]))
    c5.metric("🎯 Conversão média", f"{kpi['conversao_7d'] or 0:.2f}%", _delta(kpi["conversao_7d"], kpi["conversao_7d_ant"]))
    c6.metric("↩️ Vendas canceladas", _fmt_moeda(kpi["canceladas_7d"] or 0))
    if kpi["ultimo_dia"]:
        idade = (pd.Timestamp.now().date() - kpi["ultimo_dia"]).days
        if idade > 2:
            st.caption(f"⚠️ A planilha de Visão Geral cobre até **{kpi['ultimo_dia']:%d/%m}** ({idade} dias atrás) — os KPIs acima estão defasados; exporte uma nova.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# 3. FUNIL CONSOLIDADO
# ══════════════════════════════════════════════════════════════════════════════

secao(3, "Funil de conversão", "Da impressão à venda: descubra onde o cliente desiste.")

aba7, aba30 = st.tabs(["Últimos 7 dias", "Últimos 30 dias"])
for aba, dias in ((aba7, 7), (aba30, 30)):
    with aba:
        f = carregar_funil(dias)
        if f["impressoes"] == 0 and f["visitas"] == 0:
            st.info("Sem dados de tráfego nesta janela — importe a planilha de Performance do Produto na página 2.")
            continue

        etapas = [
            ("👁️ Impressões", f["impressoes"], "produto apareceu na busca/feed"),
            ("🖱️ Cliques", f["cliques"], "cliente abriu o anúncio"),
            ("🚶 Visitas", f["visitas"], "página do produto carregada"),
            ("🛒 Carrinhos", f["carrinhos"], "unidades adicionadas ao carrinho"),
            ("✅ Unidades vendidas", f["unidades"], "pedido feito"),
        ]
        cols = st.columns(len(etapas))
        taxas = []
        for i, (col, (nome, valor, legenda)) in enumerate(zip(cols, etapas)):
            passagem = None
            if i > 0 and etapas[i - 1][1] > 0:
                passagem = valor / etapas[i - 1][1] * 100
                taxas.append((f"{etapas[i-1][0]} → {nome}", passagem))
            col.metric(nome, f"{valor:,}".replace(",", "."), f"{passagem:.1f}% da etapa anterior" if passagem is not None else None, delta_color="off")
            col.caption(legenda)

        if taxas:
            gargalo = min(taxas, key=lambda t: t[1])
            st.warning(
                f"🔍 **Maior perda do funil:** {gargalo[0]} — só **{gargalo[1]:.1f}%** passam. "
                + ("Melhore FOTO DE CAPA e preço exibido (é o que decide o clique)." if "Cliques" in gargalo[0].split("→")[1]
                   else "Melhore descrição, fotos internas, avaliações e frete (é o que decide a compra)." )
            )

        if f["ads_gasto"] > 0:
            roas = f["ads_gmv"] / f["ads_gasto"] if f["ads_gasto"] else 0
            ctr_ads = f["ads_cliques"] / f["ads_impressoes"] * 100 if f["ads_impressoes"] else 0
            a1, a2, a3, a4 = st.columns(4)
            a1.metric("📢 Gasto em Ads", _fmt_moeda(f["ads_gasto"]))
            a2.metric("💵 GMV via Ads", _fmt_moeda(f["ads_gmv"]))
            a3.metric("📈 ROAS", f"{roas:.2f}×", "≥ 3× é saudável" , delta_color="off")
            a4.metric("🖱️ CTR dos anúncios", f"{ctr_ads:.2f}%")
            if roas < 1:
                st.error("🔴 ROAS abaixo de 1×: cada R$ 1 investido volta menos de R$ 1. Veja o plano de ação (seção 7).")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# 4. SAÚDE DA CONTA (API) — o que decide o alcance orgânico
# ══════════════════════════════════════════════════════════════════════════════

secao(4, "Saúde da conta", "O multiplicador (ou redutor) silencioso do seu alcance orgânico.")
st.markdown("""
A Shopee **rebaixa a exposição** de lojas com indicadores operacionais ruins, antes de
qualquer otimização de anúncio. As consequências oficiais por faixa de **pontos de penalidade**
(ciclo trimestral): `3+ pontos` → alerta; `6+` → produtos escondidos da busca por 28 dias;
`9+` → restrições de campanha e frete; `15+` → **congelamento da conta**. Manter isso em dia
vale mais que qualquer boost.
""")

if st.button("❤️ Atualizar saúde agora (API — 1 clique, sem planilha)"):
    with st.spinner("Consultando Account Health na API oficial..."):
        saude, msg = sincronizar_saude_conta()
    if saude is None:
        st.warning(msg)
    else:
        st.success(msg)
        carregar_saude_historico.clear()

historico_saude = carregar_saude_historico()
if historico_saude:
    ultimo_dia = max(h[0] for h in historico_saude)
    atuais = {m: float(v) for d, m, v in historico_saude if d == ultimo_dia}
    st.caption(f"Último snapshot: {ultimo_dia:%d/%m/%Y} (o histórico fica no DW — o Cérebro enxerga a tendência)")

    ROTULOS_SAUDE = {
        "saude_rating_geral": ("⭐ Rating operacional", "4=Excelente · 3=Bom · 2=Atenção · 1=Ruim"),
        "saude_pontos_penalidade": ("⚖️ Pontos de penalidade", "0 é a meta; 3+ já reduz alcance"),
        "saude_punicoes_ativas": ("🚫 Punições ativas", "qualquer valor > 0 é urgente"),
        "saude_pedidos_atrasados_agora": ("📦 Pedidos atrasados AGORA", "envie hoje para não virar ponto"),
        "saude_late_shipment_rate": ("⏰ Envio atrasado (%)", None),
        "saude_non_fulfillment_rate": ("📪 Não cumprimento (%)", None),
        "saude_anuncios_com_problema": ("🏷️ Anúncios com problema", "corrija para não perder busca"),
    }
    def _fora_da_meta(chave: str):
        """None = sem meta; (True, texto_meta) quando estourou o limite."""
        v = atuais.get(chave)
        if v is None or chave.endswith(("_meta", "_meta_min")):
            return None
        if f"{chave}_meta" in atuais:
            return v > atuais[f"{chave}_meta"], f"meta < {atuais[f'{chave}_meta']:g}"
        if f"{chave}_meta_min" in atuais:
            return v < atuais[f"{chave}_meta_min"], f"meta ≥ {atuais[f'{chave}_meta_min']:g}"
        return None

    cols = st.columns(4)
    mostrados = 0
    for chave, (rotulo, legenda) in ROTULOS_SAUDE.items():
        if chave in atuais:
            col = cols[mostrados % 4]
            situacao = _fora_da_meta(chave)
            col.metric(rotulo, f"{atuais[chave]:g}", situacao[1] if situacao else None, delta_color="off")
            col.caption(legenda or ("🔴 fora da meta!" if situacao and situacao[0] else "🟢 dentro da meta"))
            mostrados += 1

    # Veredito automático — o resumo que importa
    problemas = []
    if atuais.get("saude_rating_geral", 4) <= 2:
        problemas.append("rating operacional em nível de ATENÇÃO (a Shopee já reduz sua exposição)")
    if atuais.get("saude_pontos_penalidade", 0) > 0:
        problemas.append(f"{atuais['saude_pontos_penalidade']:g} ponto(s) de penalidade no trimestre")
    for m in atuais:
        situacao = _fora_da_meta(m)
        if situacao and situacao[0]:
            problemas.append(f"{m.replace('saude_', '').replace('_', ' ')} em {atuais[m]:g} ({situacao[1]})")
    if problemas:
        st.error(
            "🔴 **Ação necessária:** " + "; ".join(problemas[:4]) + ". "
            "**O que fazer:** despache dentro do prazo de preparo (ou aumente o prazo do anúncio em 1–2 dias "
            "para folga), evite cancelar pedido por falta de estoque (prefira pausar o anúncio) e responda o chat. "
            "Esses indicadores pesam MAIS que ads/boost no alcance."
        )
    else:
        st.success("🟢 Conta saudável — nenhuma métrica fora da meta no último snapshot.")

    metricas_expander = {m: v for m, v in sorted(atuais.items()) if not m.endswith(("_meta", "_meta_min"))}
    with st.expander(f"Ver todas as {len(metricas_expander)} métricas de saúde (com metas)"):
        def _texto_meta(m):
            if f"{m}_meta" in atuais:
                return f"< {atuais[f'{m}_meta']:g}"
            if f"{m}_meta_min" in atuais:
                return f"≥ {atuais[f'{m}_meta_min']:g}"
            return "—"
        st.dataframe(pd.DataFrame(
            [(m.replace("saude_", "").replace("_", " "), v, _texto_meta(m)) for m, v in metricas_expander.items()],
            columns=["Métrica", "Valor atual", "Meta Shopee"],
        ), hide_index=True, use_container_width=True)
else:
    st.info("Nenhum snapshot de saúde ainda — clique no botão acima para o primeiro (a API responde na hora).")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# 5. BOOST — ALCANCE GRÁTIS
# ══════════════════════════════════════════════════════════════════════════════

secao(5, "Boost de produtos", "Alcance GRÁTIS a cada 4 horas — escolha os 5 certos e clique.")
st.markdown("""
**O que é:** a Shopee deixa impulsionar **até 5 produtos por vez, de graça**; eles ganham
prioridade nas recomendações e sobem na aba da loja por **4 horas**. Depois é só repetir.

**Consequência esperada:** mais impressões orgânicas sem gastar nada — em lojas pequenas o
efeito é maior em produtos que **já convertem bem** (a Shopee testa a resposta do público).
**Risco:** nenhum. O único "custo" é escolher mal os 5 (impulsionar produto sem estoque ou
com conversão ruim desperdiça a janela). A seleção abaixo já cuida disso.
""")

try:
    dossie = carregar_dossie()
except MigracaoPendenteError as e:
    dossie = []
    st.error(str(e))

boost_atual = listar_boost_ativo()
if boost_atual is None:
    st.warning("Não foi possível consultar o boost na API agora (veja o log). Tente novamente.")
    boost_atual = []
elif boost_atual:
    nomes_boost = {d["item_id"]: d["nome_produto"] for d in dossie}
    st.info("⚡ Impulsionados agora: " + ", ".join(str(nomes_boost.get(i, i)) for i in boost_atual))

if dossie:
    # Score determinístico por ITEM (boost é por anúncio, não por variação):
    # conversão pesa mais (a Shopee amplia o que já converte), vendas recentes
    # confirmam demanda e estoque zero desclassifica (janela desperdiçada).
    por_item = {}
    for d in dossie:
        item = por_item.setdefault(d["item_id"], {
            "nome": d["nome_produto"], "conv": 0.0, "vendas": 0, "estoque": 0, "lucro": 0.0,
        })
        item["conv"] = max(item["conv"], d.get("TRAFEGO_taxa_conversao_perc") or 0)
        item["vendas"] += d.get("vendas_7d_reais") or 0
        item["estoque"] += d.get("estoque_shopee_hoje") or 0
        item["lucro"] += d.get("lucro_liquido_real_7d") or 0

    candidatos = sorted(
        (
            (iid, m) for iid, m in por_item.items()
            if iid > 0 and m["estoque"] > 0 and iid not in set(boost_atual)
        ),
        key=lambda x: (x[1]["conv"] * 2 + x[1]["vendas"] + (5 if x[1]["lucro"] > 0 else 0)),
        reverse=True,
    )[:8]

    if candidatos:
        st.markdown("**Sugestão local (sem IA):** os melhores candidatos ao boost de agora são:")
        fotos = carregar_fotos()
        df_cand = pd.DataFrame([
            {
                "Impulsionar": i < 5,
                "item_id": iid,
                "Foto": fotos.get(iid),
                "Produto": m["nome"][:60],
                "Conversão 7d": f"{m['conv']:.1f}%",
                "Vendas 7d": m["vendas"],
                "Estoque": m["estoque"],
                "Lucro 7d": _fmt_moeda(m["lucro"]),
            }
            for i, (iid, m) in enumerate(candidatos)
        ])
        selecao = st.data_editor(
            df_cand, hide_index=True, use_container_width=True,
            disabled=[c for c in df_cand.columns if c != "Impulsionar"],
            column_config={"item_id": None, "Foto": st.column_config.ImageColumn("Foto", width="small")},
            key="editor_boost",
        )
        escolhidos = [int(r["item_id"]) for _, r in selecao.iterrows() if r["Impulsionar"]][:5]
        if st.button(f"🚀 Impulsionar {len(escolhidos)} produto(s) agora (grátis)", type="primary", disabled=not escolhidos):
            sucesso, falhas = impulsionar_itens(escolhidos)
            for iid in sucesso:
                salvar_log_acao(iid, None, "BOOST_ITEM", "Boost gratuito de 4h via Visão Central",
                                {"estrategia": "BOOST_ITEM"}, "SUCESSO")
            if sucesso:
                st.success(f"✅ {len(sucesso)} produto(s) impulsionado(s) por 4 horas: {sucesso}")
            for iid, motivo in falhas:
                st.error(f"Item {iid} recusado pela Shopee: {motivo} (em cooldown de boost anterior?)")
            st.caption("⏰ Repita a cada 4 horas para manter o efeito. Dica: de manhã, ao meio-dia e à noite.")
    else:
        st.info("Sem candidatos elegíveis (estoque zerado ou tudo já impulsionado).")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# 6. VOUCHER DE CHECKOUT — ataca o abandono de carrinho
# ══════════════════════════════════════════════════════════════════════════════

secao(6, "Voucher de checkout", "Ataca diretamente o abandono de carrinho, com custo controlado.")

funil_7d = carregar_funil(7)
abandonos_7d = max(0, funil_7d["carrinhos"] - funil_7d["unidades"])
taxa_abandono = (abandonos_7d / funil_7d["carrinhos"] * 100) if funil_7d["carrinhos"] else 0.0
economia = carregar_economia_real()

st.markdown(f"""
**Por que esta alavanca:** nos últimos 7 dias, **{funil_7d['carrinhos']} unidades entraram no
carrinho e só {funil_7d['unidades']} viraram venda** — {taxa_abandono:.0f}% de abandono. Um cupom
visível no checkout é o empurrão clássico para quem parou na última etapa.

**Dois números diferentes comandam a conta (não confundir):**
o **gasto mínimo** do cupom é sobre o que o **cliente paga** na cesta; já o **desconto sai do
SEU repasse** — então quem limita o tamanho do desconto é o seu ganho líquido por pedido,
não o preço de venda.
""")

# Base 100% real: cesta média vinda dos itens de pedido; ganho líquido vindo do
# escrow liquidado. Nada de "Vendas (BRL)" bruto da planilha da Shopee.
cesta_real = economia["cesta_media_cliente"]
repasse_real = economia["repasse_medio_pedido"]
base_confiavel = economia["pedidos_liquidados"] >= 10

col_e1, col_e2 = st.columns(2)
col_e1.metric("🛒 Cesta média (o que o cliente paga)",
              _fmt_moeda(cesta_real) if cesta_real is not None else "—")
col_e1.caption(f"média real dos {economia['pedidos_30d']} pedidos de 30d (soma dos itens, sem frete)")
col_e2.metric("💵 Ganho líquido médio por pedido",
              _fmt_moeda(repasse_real) if repasse_real is not None else "—")
col_e2.caption(
    f"repasse REAL do escrow — {economia['pedidos_liquidados']} pedidos liquidados em 30d"
    + ("" if base_confiavel else " ⚠️ amostra pequena, confira o valor abaixo")
)

if repasse_real is None or not base_confiavel:
    st.warning(
        "Poucos pedidos liquidados no escrow para calcular seu ganho médio com segurança. "
        "Informe abaixo o valor que você conhece da sua operação — nada será assumido."
    )
ganho_liquido_pedido = st.number_input(
    "Seu ganho líquido médio por pedido (R$) — usado em toda a conta abaixo:",
    min_value=0.5,
    value=float(round(repasse_real, 2)) if repasse_real else 9.0,
    step=0.5,
    help="Pré-preenchido com a média real do escrow quando ela existe; ajuste se souber melhor.",
)

vouchers_ativos = listar_vouchers("ongoing")
vouchers_agendados = listar_vouchers("upcoming")
if vouchers_ativos is None:
    st.warning("Não foi possível consultar os vouchers na API agora — tente de novo.")
else:
    todos_vouchers = [("ongoing", v) for v in vouchers_ativos] + [("upcoming", v) for v in (vouchers_agendados or [])]
    if todos_vouchers:
        st.markdown("**Vouchers existentes:**")
        st.dataframe(pd.DataFrame([
            {
                "Código": v.get("voucher_code", "—"),
                "Nome": v.get("voucher_name", "—"),
                "Status": "🟢 ativo" if situ == "ongoing" else "🕓 agendado",
                "Desconto": (f"{v['percentage']}% (até {_fmt_moeda(v.get('max_price', 0))})"
                             if v.get("reward_type") == 2 else _fmt_moeda(v.get("discount_amount", 0))),
                "Gasto mínimo": _fmt_moeda(v.get("min_basket_price", 0)),
                "Usos": f"{v.get('current_usage', 0)}/{v.get('usage_quantity', 0)}",
                "Termina em": pd.Timestamp(v["end_time"], unit="s").strftime("%d/%m/%Y") if v.get("end_time") else "—",
            }
            for situ, v in todos_vouchers
        ]), hide_index=True, use_container_width=True)

        opcoes_encerrar = {
            f"{v.get('voucher_code')} — {v.get('voucher_name')}": (v.get("voucher_id"), situ == "ongoing")
            for situ, v in todos_vouchers
        }
        col_sel, col_end = st.columns([3, 1])
        escolhido = col_sel.selectbox("Encerrar/excluir um voucher:", ["—"] + list(opcoes_encerrar), label_visibility="collapsed")
        if col_end.button("🛑 Encerrar", disabled=escolhido == "—"):
            vid, iniciado = opcoes_encerrar[escolhido]
            ok, msg_end = encerrar_voucher(vid, ja_iniciado=iniciado)
            (st.success if ok else st.error)(msg_end)
            if ok:
                salvar_log_acao(None, None, "ENCERRAR_VOUCHER", f"Voucher {escolhido} encerrado via Visão Central",
                                {"estrategia": "ENCERRAR_VOUCHER"}, "SUCESSO")

# Sugestão determinística: desconto limitado pelo GANHO LÍQUIDO (nunca mais de
# ~30% dele — cada uso sai do repasse); gasto mínimo ancorado na CESTA do
# cliente (~20% acima, para o cupom puxar o pedido para cima).
desconto_sugerido = float(min(5.0, max(2.0, round(ganho_liquido_pedido * 0.30))))
base_cesta = cesta_real if cesta_real is not None else 25.0
min_gasto_sugerido = float(max(15, round(base_cesta * 1.2 / 5) * 5))
usos_sugeridos = 30

st.markdown("**Criar voucher novo (sugestão calculada dos SEUS números, ajuste à vontade):**")
c_v1, c_v2, c_v3, c_v4 = st.columns(4)
v_desconto = c_v1.number_input(
    "Desconto (R$)", min_value=1.0, value=desconto_sugerido, step=1.0,
    help=f"Sugerido: ~30% do seu ganho líquido por pedido ({_fmt_moeda(ganho_liquido_pedido)}) — o desconto sai do seu repasse.")
v_min = c_v2.number_input(
    "Gasto mínimo (R$)", min_value=5.0, value=min_gasto_sugerido, step=5.0,
    help=f"Sugerido: ~20% acima da cesta média real do cliente ({_fmt_moeda(base_cesta)}) para aumentar o pedido.")
v_usos = c_v3.number_input("Limite de usos", min_value=1, value=usos_sugeridos, step=5)
v_dias = c_v4.number_input("Duração (dias)", min_value=1, max_value=90, value=7)

custo_maximo = v_desconto * v_usos
ganho_por_recuperado = ganho_liquido_pedido - v_desconto
caronas_pagaveis = int(ganho_por_recuperado // v_desconto) if v_desconto > 0 else 0
recuperacao_min, recuperacao_max = int(abandonos_7d * 0.05), max(1, int(abandonos_7d * 0.15))
lucro_extra_min = recuperacao_min * ganho_por_recuperado
lucro_extra_max = recuperacao_max * ganho_por_recuperado

if ganho_por_recuperado <= 0:
    st.error(
        f"🔴 **Desconto maior que o seu ganho por pedido** ({_fmt_moeda(ganho_liquido_pedido)}): "
        "cada uso do cupom daria PREJUÍZO. Reduza o desconto ou aumente o gasto mínimo."
    )
else:
    st.info(
        f"📐 **A conta, em LUCRO LÍQUIDO (não em vendas brutas):** cada pedido recuperado deixa "
        f"~**{_fmt_moeda(ganho_por_recuperado)}** líquidos ({_fmt_moeda(ganho_liquido_pedido)} de ganho − "
        f"{_fmt_moeda(v_desconto)} do cupom, que sai do seu repasse). Cada cliente que usaria o cupom "
        f"mas compraria mesmo sem ele ('carona') custa {_fmt_moeda(v_desconto)} — ou seja, "
        f"**1 pedido recuperado paga até {caronas_pagaveis} carona(s)**. "
        f"**Previsão conservadora** (5–15% dos {abandonos_7d} abandonos/semana recuperados): "
        f"**{recuperacao_min}–{recuperacao_max} pedidos extras/semana ≈ "
        f"{_fmt_moeda(lucro_extra_min)}–{_fmt_moeda(lucro_extra_max)} de lucro líquido adicional**. "
        f"Teto de exposição: {_fmt_moeda(custo_maximo)} ({v_usos} usos × {_fmt_moeda(v_desconto)}), "
        f"e cupom não usado não custa nada. Como o gasto mínimo ({_fmt_moeda(v_min)}) fica acima da "
        f"cesta média, pedidos com cupom tendem a ser maiores — a previsão acima NÃO conta esse ganho."
    )

if st.button("🎟️ Criar voucher agora na Shopee", type="primary", disabled=ganho_por_recuperado <= 0):
    nome_voucher = f"Volta pro carrinho {pd.Timestamp.now():%d/%m}"
    ok, resultado = criar_voucher_loja(nome_voucher, v_desconto, v_min, int(v_usos), int(v_dias))
    if ok:
        salvar_log_acao(
            None, None, "CRIAR_VOUCHER",
            f"Voucher R$ {v_desconto:.2f} acima de R$ {v_min:.2f}, {int(v_usos)} usos, {int(v_dias)}d (id {resultado})",
            {"estrategia": "CRIAR_VOUCHER", "custo_maximo": custo_maximo,
             "ganho_liquido_por_pedido_usado_na_conta": ganho_liquido_pedido,
             "previsao_pedidos_extras": [recuperacao_min, recuperacao_max],
             "previsao_lucro_extra": [round(lucro_extra_min, 2), round(lucro_extra_max, 2)]},
            "SUCESSO",
        )
        st.success(f"✅ Voucher criado (id {resultado})! Ativo em ~15 min, por {int(v_dias)} dias. "
                   "Compare os usos e a taxa de abandono da seção 3 na próxima semana.")
    else:
        st.error(resultado)

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# 7. RADAR POR PRODUTO (API — sem planilha)
# ══════════════════════════════════════════════════════════════════════════════

secao(7, "Radar por produto", "Views e curtidas direto da API — sem exportar nada.")
st.markdown(
    "Views e curtidas **acumuladas** de cada anúncio. Tirando um snapshot por dia, o delta "
    "entre snapshots vira o 'tráfego do dia' — um termômetro independente das planilhas."
)

if st.button("📸 Tirar snapshot de views/curtidas agora (API)"):
    with st.spinner("Consultando a API item a item..."):
        qtd, msg = sincronizar_metricas_api_produtos()
    if qtd:
        st.success(f"Snapshot de {qtd} produtos gravado no DW.")
        carregar_radar_api.clear()
    else:
        st.warning(msg)

radar = carregar_radar_api()
if radar:
    fotos_radar = carregar_fotos()
    df_radar = pd.DataFrame([
        {
            "Foto": fotos_radar.get(_iid),
            "Produto": nome[:60],
            "Views acumuladas": int(views or 0),
            "Views desde o último snapshot": (int(views - views_ant) if views is not None and views_ant is not None else None),
            "Curtidas": int(curtidas or 0),
            "Vendas acumuladas": int(vendas or 0),
            "Avaliações": int(avals or 0),
            "Snapshot": snap.strftime("%d/%m") if snap else "—",
        }
        for (_iid, nome, views, views_ant, _dant, curtidas, vendas, avals, snap) in radar
    ])
    st.dataframe(df_radar, hide_index=True, use_container_width=True,
                 column_config={"Foto": st.column_config.ImageColumn("Foto", width="small")})
    st.caption(
        "💡 Como ler: produto com MUITAS views e POUCAS vendas acumuladas tem problema de página "
        "(preço/fotos/avaliações); com POUCAS views, tem problema de alcance (título/boost/ads)."
    )
else:
    st.info("Nenhum snapshot ainda — clique no botão acima para o primeiro.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# 8. PLANO DE AÇÃO DETERMINÍSTICO (custo de IA: R$ 0,00)
# ══════════════════════════════════════════════════════════════════════════════

secao(8, "Plano de ação", "Calculado localmente, com consequências e previsões por produto.")

def _consequencia(d: dict) -> str:
    """Traduz a recomendação heurística em consequência de NÃO agir + o que esperar ao agir."""
    if d.get("ADS_gasto_7d", 0) > 0 and d.get("ADS_roas_atual", 0) < 1:
        perda = d["ADS_gasto_7d"] * 0.9
        return (f"Não agir: ~{_fmt_moeda(perda)}/semana continuam virando prejuízo em ads. "
                f"Agir (pausar/ajustar): o gasto para imediatamente; vendas orgânicas não são afetadas.")
    if d.get("LOGISTICA_dias_estoque_restante", 999) < 7:
        return ("Não agir: ruptura de estoque em menos de 7 dias — anúncio perde posição no ranking "
                "e demora semanas para recuperar. Agir (reabastecer/subir preço): margem protegida.")
    if d.get("lucro_liquido_real_7d", 0) < 0 and d.get("vendas_7d_reais", 0) > 0:
        return (f"Não agir: cada venda AMPLIA o prejuízo (lucro 7d: {_fmt_moeda(d['lucro_liquido_real_7d'])}). "
                "Agir (subir preço/rever custo): vendas podem cair, mas passam a dar lucro.")
    if d.get("taxa_cancelamento_7d_perc", 0) > 10:
        return ("Não agir: cancelamentos altos pioram a saúde da conta (seção 4) e rebaixam a busca. "
                "Agir: revisar prazo de preparo, embalagem e descrição para alinhar expectativa.")
    if d.get("TRAFEGO_taxa_conversao_perc", 0) >= 3:
        return ("Produto converte acima da média: cada visita extra vira venda com facilidade. "
                "Agir (boost grátis + considerar ads): alcance multiplicado com risco baixo.")
    return "Sem risco iminente. Monitorar os próximos 7 dias; priorize os itens acima."


if dossie:
    alertas = heuristicas.gerar_alertas_criticos(dossie)
    if alertas:
        st.subheader("🚨 Alertas críticos")
        for a in alertas[:8]:
            st.error(f"{a['nivel']} — **{a['produto']}**: {a['mensagem']}")

    sem_custo_mapeado = sum(1 for d in dossie if not d.get("custo_fab_real"))
    if sem_custo_mapeado:
        st.warning(
            f"⚠️ **{sem_custo_mapeado} de {len(dossie)} variações não têm custo de fabricação mapeado** "
            "(filamento/energia/embalagem). Para elas, o 'Lucro previsto' abaixo considera custo de "
            "produção ZERO — ou seja, está superestimado e aparece marcado com ⚠️. "
            "Mapeie os insumos na página 🏭 Engenharia de Fábrica para números reais."
        )

    ranking = sorted(dossie, key=lambda d: heuristicas.calcular_score_urgencia(d), reverse=True)
    fotos_plano = carregar_fotos()
    linhas_plano = []
    for d in ranking[:10]:
        score = heuristicas.calcular_score_urgencia(d)
        conf, detalhe_conf, _ = heuristicas.classificar_confianca_evidencia(d)
        faixa = heuristicas.intervalo_demanda_exploratorio(d, d.get("previsao_vendas_7d", 0))
        lucro_previsto = _fmt_moeda(d.get("previsao_lucro_7d", 0))
        if not d.get("custo_fab_real"):
            lucro_previsto += " ⚠️ sem custo fab."
        linhas_plano.append({
            "Foto": fotos_plano.get(d["item_id"]),
            "Urgência": score,
            "Produto": f"{d['nome_produto'][:40]} ({d['nome_variacao'][:20]})",
            "Cluster": d.get("cluster_mercado", "—"),
            "Ação recomendada": d.get("recomendacao_executiva", "—"),
            "Consequência (agir vs não agir)": _consequencia(d),
            "Previsão 7d (un.)": f"{d.get('previsao_vendas_7d', 0)} (faixa {faixa[0]}–{faixa[1]})",
            "Lucro previsto 7d": lucro_previsto,
            "Evidência": f"{conf} — {detalhe_conf}",
        })
    st.dataframe(pd.DataFrame(linhas_plano), hide_index=True, use_container_width=True, height=420,
                 column_config={"Foto": st.column_config.ImageColumn("Foto", width="small")})
    st.caption(
        "🧮 Tudo acima foi calculado pelas heurísticas locais do pacote `cerebro/` — nenhuma chamada de IA. "
        "As previsões usam elasticidade, tendência semanal e capacidade de material; a coluna Evidência "
        "diz o quanto confiar. Para o parecer estratégico completo (com plano de preço por variação), "
        "rode a auditoria na página 🧠 — ela usa cache semântico e só paga por produto que MUDOU."
    )
else:
    st.info("Dossiê vazio — sincronize catálogo e pedidos na página 2 para liberar o plano de ação.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# 9. CATÁLOGO DE ALAVANCAS (o que mais dá para fazer — e o que cada uma custa)
# ══════════════════════════════════════════════════════════════════════════════

with st.expander("🧰 Todas as alavancas de alcance disponíveis (integradas e futuras)"):
    st.markdown("""
| Alavanca | Status | Custo | Efeito esperado | Risco / consequência |
|---|---|---|---|---|
| **🚀 Boost (5 itens/4h)** | ✅ Integrada (seção 5) | Grátis | + impressões nas recomendações por 4h | Nenhum; só a janela desperdiçada se escolher mal |
| **⚡ Promoção relâmpago** (`discount`) | ✅ Integrada (página 3 executa) | Margem menor durante a promo | Selo de desconto → +CTR e +conversão | Preço-âncora piscando demais "vicia" o cliente; use 24–48h |
| **📦 Combo Leve 2** (`bundle_deal`) | ✅ Integrada (página 3 executa) | % de desconto no 2º item | Ticket médio maior, frete diluído | Margem por unidade cai; ideal p/ itens leves |
| **💲 Ajuste de preço** | ✅ Integrada (página 3 executa) | — | Reposiciona na faixa de busca | Elasticidade: o dossiê mede o efeito real após 7 dias |
| **🎟️ Voucher da loja** (`voucher`) | ✅ Integrada (seção 6) | Valor do cupom × usos | Recupera carrinho abandonado (taxa da seção 3) | Cupom generoso demais come a margem |
| **➕ Leve Junto** (`add_on_deal`) | 🔜 Não integrada | Desconto no acessório | Vende acessório junto ao principal | Estoque do acessório precisa acompanhar |
| **🎁 Presente por seguir** (`follow_prize`) | 🔜 Não integrada | Pequeno cupom | +seguidores → notificações grátis nas próximas promos | Baixo |
| **⭐ Destaques da loja** (`top_picks`) | 🔜 Não integrada | Grátis | Vitrine cruzada dentro das suas páginas de produto | Nenhum |
| **❤️ Saúde da conta** (`account_health`) | ✅ Integrada (seção 4) | Grátis | Protege o alcance orgânico (pontos escondem produtos da busca) | Nenhum |
| **📢 API de Ads** | ⛔ Sem permissão p/ apps in-house nesta conta (probe retornou 404) | — | Automatizaria o export de Ads | Continue com a planilha da Central de Anúncios |

As alavancas 🔜 já são suportadas pela sua conta (mesmos módulos de Marketing da API);
se quiser, a próxima iteração integra qualquer uma delas com 1 botão + registro no diário de ações.
""")
