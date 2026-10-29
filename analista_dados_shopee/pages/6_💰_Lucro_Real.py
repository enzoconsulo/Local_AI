"""
pages/6_💰_Lucro_Real.py
========================
A aba de LUCRO: quanto sobra de verdade em cada produto, com a conta aberta.

Decisões de desenho:
  - Tudo vem das fontes únicas da migração 19: vw_custo_fabricacao_variacao
    (custo por PEÇA, uma linha por variação) e vw_financeiro_item_pedido (uma
    linha por item de pedido, com o repasse da Shopee rateado e detalhado).
    Nenhuma conta de custo é refeita aqui: o chat errou justamente por refazer
    (juntou engenharia com vendas diárias e somou o custo 7 vezes).
  - Lucro = repasse da Shopee (pedido ainda não pago: estimado pela fração que
    o próprio produto costuma receber) + recarga de anúncios − custo de
    fabricação − gasto real de anúncios. A recarga (parte do preço descontada
    para o SALDO de anúncios) volta porque o anúncio entra uma vez só, pelo
    gasto real; sem planilha de anúncios recente, a recarga é usada no lugar.
  - Editar o preço do kg de um filamento muda apenas o CÁLCULO de lucro —
    nunca o preço de venda na Shopee.
  - O mapeamento enxuto grava peso/filamento/embalagem em TODAS as variações
    do item (tempo, máquina e perda ficam na página 🏭 — o upsert preserva).
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pandas as pd
import streamlit as st

from utils.db_pool import get_connection
from workers.sync_catalogo import sincronizar_catalogo
from workers.sync_pedidos import detalhar_repasses_pendentes, sincronizar_pedidos
from workers.importar_planilhas import (
    obter_ultima_sincronizacao,
    registrar_sincronizacao,
    fatiar_periodo,
)
from cerebro.config import MigracaoPendenteError
from cerebro.dossie import gerar_dossie_produtos_com_memoria

st.set_page_config(page_title="Lucro Real", page_icon="💰", layout="wide")

from utils.ui import aplicar_estilo, cabecalho, nota, secao
aplicar_estilo()
cabecalho(
    "💰", "Lucro Real por Produto",
    "Repasse da Shopee − fabricação − anúncios, com a conta aberta linha a linha. 100% local, zero IA.",
)

PERIODOS = {"30 dias": 30, "90 dias": 90, "Tudo": 3650}
FORMATO_MOEDA = "R$ %.2f"


def _fmt_moeda(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _dataframe(cur) -> pd.DataFrame:
    """Resultado do cursor em DataFrame, com Decimal do Postgres virando float."""
    colunas = [c[0] for c in cur.description]
    df = pd.DataFrame(cur.fetchall(), columns=colunas)
    for coluna in df.columns:
        if df[coluna].map(lambda v: isinstance(v, Decimal)).any():
            df[coluna] = df[coluna].map(lambda v: float(v) if v is not None else None).astype(float)
    return df


# ══════════════════════════════════════════════════════════════════════════════
# CARREGADORES
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=120, show_spinner=False)
def carregar_materiais():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id_material, nome, custo_por_unidade, COALESCE(estoque_atual, 0)
                FROM dim_materiais ORDER BY nome;
            """)
            return cur.fetchall()


@st.cache_data(ttl=120, show_spinner=False)
def carregar_mapeamento_itens():
    """Uma linha por PRODUTO com o mapeamento representativo das variações."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    p.item_id, p.nome_atual, p.imagem_url,
                    COUNT(v.model_id)                             AS variacoes,
                    COUNT(eng.model_id)                           AS variacoes_mapeadas,
                    MODE() WITHIN GROUP (ORDER BY eng.id_material) AS id_material,
                    ROUND(AVG(eng.peso_gramas), 1)                AS peso_gramas,
                    ROUND(AVG(COALESCE(eng.custo_embalagem, 0)), 2) AS custo_embalagem
                FROM dim_produtos p
                JOIN dim_variacoes v ON v.item_id = p.item_id
                LEFT JOIN map_engenharia_produto eng ON eng.model_id = v.model_id
                WHERE p.status_shopee = 'NORMAL' AND p.item_id > 0
                  AND v.nome_variacao NOT ILIKE '%%Excluída%%'
                  AND v.nome_variacao NOT ILIKE '%%Excluida%%'
                GROUP BY p.item_id, p.nome_atual, p.imagem_url
                ORDER BY p.nome_atual;
            """)
            return cur.fetchall()


@st.cache_data(ttl=300, show_spinner="Calculando lucro por produto (local, sem IA)...")
def carregar_dossie():
    return gerar_dossie_produtos_com_memoria()


@st.cache_data(ttl=120, show_spinner=False)
def carregar_produtos_vendidos():
    """Produtos com venda nos últimos 12 meses, do mais vendido para o menos."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT f.item_id, p.nome_atual, p.imagem_url, SUM(f.quantidade) AS unidades
                FROM vw_financeiro_item_pedido f
                JOIN dim_produtos p ON p.item_id = f.item_id
                WHERE f.data >= CURRENT_DATE - 365
                GROUP BY f.item_id, p.nome_atual, p.imagem_url
                ORDER BY unidades DESC, p.nome_atual;
            """)
            return cur.fetchall()


@st.cache_data(ttl=120, show_spinner=False)
def carregar_pedidos_do_produto(item_id: int, dias: int) -> pd.DataFrame:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM vw_financeiro_item_pedido
                WHERE item_id = %s AND data >= CURRENT_DATE - %s
                ORDER BY data_hora_criacao DESC;
            """, (item_id, dias))
            return _dataframe(cur)


@st.cache_data(ttl=120, show_spinner=False)
def carregar_custo_do_produto(item_id: int) -> pd.DataFrame:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT variacao, material, preco_material, unidade_material, peso_gramas,
                       maquina, custo_maquina_hora, tempo_impressao_minutos, perda_percentual,
                       custo_material, custo_maquina, custo_embalagem, custo_perda, custo_total
                FROM vw_custo_fabricacao_variacao
                WHERE item_id = %s
                ORDER BY variacao;
            """, (item_id,))
            return _dataframe(cur)


@st.cache_data(ttl=120, show_spinner=False)
def carregar_anuncios_do_produto(item_id: int, dias: int) -> tuple[float, bool]:
    """(gasto real de anúncios do produto na janela, planilha de anúncios recente?)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    COALESCE(SUM(investimento) FILTER (
                        WHERE item_id = %s AND data_registro >= CURRENT_DATE - %s), 0),
                    COALESCE(MAX(data_registro) >= CURRENT_DATE - 7, FALSE)
                FROM fato_ads_performance_produto;
            """, (item_id, dias))
            gasto, recente = cur.fetchone()
            return float(gasto or 0), bool(recente)


def limpar_caches():
    carregar_materiais.clear()
    carregar_mapeamento_itens.clear()
    carregar_dossie.clear()
    carregar_produtos_vendidos.clear()
    carregar_pedidos_do_produto.clear()
    carregar_custo_do_produto.clear()
    carregar_anuncios_do_produto.clear()


# ══════════════════════════════════════════════════════════════════════════════
# CONTA ABERTA (usada pelo Raio-X)
# ══════════════════════════════════════════════════════════════════════════════

# Linhas que aparecem mesmo zeradas: sem elas a conta não se lê.
LINHAS_SEMPRE_VISIVEIS = {
    "Preço de venda", "= Repasse da Shopee", "− Custo de fabricação",
    "= Lucro antes de anúncios", "− Anúncios", "= Lucro",
}


def linhas_para_onde_vai_o_dinheiro(df: pd.DataFrame, gasto_ads: float, ads_recentes: bool):
    """Monta a conta, do preço ao lucro, somando os itens de pedido do período.

    Pedidos já pagos entram com cada desconto real; pedidos ainda não pagos
    entram numa linha só de taxas estimadas. A soma das linhas até o repasse
    fecha com o repasse (a linha de arredondamento mostra qualquer centavo de
    diferença do rateio entre itens de um mesmo pedido).
    """
    reais = df[df["origem_repasse"] == "REAL"]
    estimados = df[df["origem_repasse"] != "REAL"]

    def real(coluna):
        return float(reais[coluna].fillna(0).sum())

    valor = float(df["valor_item"].sum())
    recarga = float(df["recarga_ads"].fillna(0).sum())
    repasse = float(df["repasse"].sum())
    custo_fab = float(df["custo_fabricacao"].sum())
    lucro_antes_ads = float(df["lucro_antes_ads"].sum())
    custo_ads = gasto_ads if ads_recentes else recarga

    linhas = [
        ("Preço de venda", valor, "O que o comprador pagou pelos produtos."),
        ("− Comissão da Shopee", -real("comissao_shopee"), "Percentual sobre o preço."),
        ("− Taxa de serviço", -real("taxa_servico"), "Parte variável + parte fixa por item vendido."),
        ("− Taxa de transação", -real("taxa_transacao"), "Só a parte cobrada de você (parcelamento pago pelo comprador não entra)."),
        ("− Comissão de afiliado", -real("comissao_afiliado"), "Venda que chegou por um afiliado da Shopee."),
        ("− Cupom da loja", -real("cupom_vendedor"), "Cupom que você ofereceu."),
        ("− Seguro de frete", -real("seguro_frete"), "Proteção de frete cobrada por pedido."),
        ("± Frete pago pelo vendedor", real("frete_liquido_vendedor"), "Negativo = parte do frete saiu de você."),
        ("− Reembolsos de devolução", -real("reembolso_devolucao"), "Pedido devolvido: o valor volta para o comprador."),
        ("− Frete de devolução", -real("custo_frete_reverso"), "Frete reverso pago por você."),
        ("± Ajustes da Shopee depois do pagamento", real("ajuste_pos_venda"),
         "Negativo = a Shopee tirou dinheiro depois (ex.: devolução tardia)."),
        ("− Outros ajustes", -real("outros_ajustes"), "Diferença que fecha a conta com o repasse pago."),
        ("− Taxas de pedidos ainda não pagos (estimadas)", -float(estimados["retido_shopee"].sum()),
         "Estimativa pela fração que este produto costuma receber da Shopee."),
        ("− Recarga do saldo de anúncios", -recarga, "Parte do preço que a Shopee desconta e põe no seu saldo de anúncios."),
    ]
    diferenca = round(repasse - sum(total for _, total, _ in linhas), 2)
    if abs(diferenca) >= 0.01:
        linhas.append(("± Arredondamentos", diferenca, "Centavos do rateio entre itens de um mesmo pedido."))
    linhas += [
        ("= Repasse da Shopee", repasse, "O que cai na sua conta."),
        ("+ Recarga de anúncios devolvida", recarga, "Não é custo: virou saldo de anúncios. O anúncio entra abaixo, uma vez só."),
        ("− Custo de fabricação", -custo_fab, "Custo por peça (seção 1) × unidades vendidas."),
        ("= Lucro antes de anúncios", lucro_antes_ads, ""),
        ("− Anúncios", -custo_ads,
         "Gasto real da planilha de anúncios." if ads_recentes
         else "Planilha de anúncios sem dados dos últimos 7 dias: usando a recarga descontada do repasse."),
        ("= Lucro", lucro_antes_ads - custo_ads, "O que sobra de verdade."),
    ]
    return linhas


aba_lucro, aba_raio_x, aba_custos = st.tabs(
    ["💰 Lucro por produto", "🔍 Raio-X do produto", "🧵 Mapear custos (2 passos)"]
)

# ══════════════════════════════════════════════════════════════════════════════
# ABA 3 — MAPEAMENTO RÁPIDO DE CUSTOS
# ══════════════════════════════════════════════════════════════════════════════

with aba_custos:
    secao(1, "Seus filamentos e o preço do quilo",
          "Pagou mais caro ou mais barato num lote? Edite o preço aqui — muda só o cálculo de lucro, nunca o preço de venda na Shopee.")

    materiais = carregar_materiais()
    df_mat = pd.DataFrame(
        [{"id": m[0], "Filamento": m[1], "Preço do kg (R$)": float(m[2]),
          "R$ por grama": float(m[2]) / 1000, "Estoque (kg)": float(m[3])} for m in materiais]
        or [{"id": None, "Filamento": "PLA Branco", "Preço do kg (R$)": 90.0, "R$ por grama": 0.09, "Estoque (kg)": 1.0}]
    )
    edit_mat = st.data_editor(
        df_mat, num_rows="dynamic", hide_index=True, use_container_width=True,
        column_config={
            "id": None,  # oculto — controle interno
            "R$ por grama": st.column_config.NumberColumn(
                "R$ por grama", disabled=True, format="R$ %.4f",
                help="Preço do kg ÷ 1.000. É o valor multiplicado pelo peso da peça.",
            ),
        },
        key="editor_materiais",
    )
    if st.button("💾 Salvar filamentos"):
        salvos, novos = 0, 0
        with get_connection() as conn:
            with conn.cursor() as cur:
                for _, r in edit_mat.iterrows():
                    nome = str(r["Filamento"] or "").strip()
                    if not nome:
                        continue
                    preco = float(r["Preço do kg (R$)"] or 0)
                    estoque = float(r["Estoque (kg)"] or 0)
                    if pd.notna(r["id"]) and r["id"] is not None:
                        cur.execute("""
                            UPDATE dim_materiais SET nome=%s, custo_por_unidade=%s,
                                   estoque_atual=%s, data_atualizacao=CURRENT_TIMESTAMP
                            WHERE id_material=%s;
                        """, (nome, preco, estoque, int(r["id"])))
                        salvos += 1
                    else:
                        cur.execute("""
                            INSERT INTO dim_materiais (nome, tipo, custo_por_unidade, unidade_medida, estoque_atual)
                            VALUES (%s, 'Filamento', %s, 'kg', %s);
                        """, (nome, preco, estoque))
                        novos += 1
        limpar_caches()
        st.success(f"✅ {salvos} filamento(s) atualizado(s), {novos} novo(s). O lucro usa os preços novos daqui pra frente.")

    st.divider()
    secao(2, "Filamento e peso de cada produto",
          "Uma linha por produto — vale para TODAS as variações. Se alguma for muito diferente, refine depois na página 🏭.")

    materiais = carregar_materiais()
    if not materiais:
        st.warning("Cadastre ao menos 1 filamento no Passo 1 (e salve) para liberar este passo.")
    else:
        nome_por_id = {m[0]: m[1] for m in materiais}
        id_por_nome = {m[1]: m[0] for m in materiais}
        itens = carregar_mapeamento_itens()
        df_itens = pd.DataFrame([
            {
                "item_id": it[0],
                "Foto": it[2],
                "Produto": it[1][:70],
                "Filamento": nome_por_id.get(it[5]),
                "Peso por peça (g)": float(it[6]) if it[6] else None,
                "Embalagem (R$)": float(it[7]) if it[7] else 0.0,
                "Situação": "✅" if it[4] >= it[3] and it[3] > 0 else ("◐ parcial" if it[4] else "—"),
            }
            for it in itens
        ])
        edit_itens = st.data_editor(
            df_itens, hide_index=True, use_container_width=True, height=560,
            column_config={
                "item_id": None,
                "Foto": st.column_config.ImageColumn("Foto", width="small"),
                "Produto": st.column_config.TextColumn("Produto", disabled=True),
                "Filamento": st.column_config.SelectboxColumn("Filamento", options=list(id_por_nome)),
                "Peso por peça (g)": st.column_config.NumberColumn("Peso por peça (g)", min_value=0.5, step=0.5),
                "Embalagem (R$)": st.column_config.NumberColumn("Embalagem (R$)", min_value=0.0, step=0.25),
                "Situação": st.column_config.TextColumn("Situação", disabled=True),
            },
            key="editor_itens",
        )
        if st.button("💾 Salvar mapeamento e recalcular lucro", type="primary"):
            gravados, pulados = 0, 0
            with get_connection() as conn:
                with conn.cursor() as cur:
                    for _, r in edit_itens.iterrows():
                        filamento = r["Filamento"]
                        peso = r["Peso por peça (g)"]
                        if not filamento or pd.isna(peso) or float(peso) <= 0:
                            pulados += 1
                            continue
                        cur.execute("""
                            SELECT model_id FROM dim_variacoes
                            WHERE item_id = %s
                              AND nome_variacao NOT ILIKE '%%Excluída%%'
                              AND nome_variacao NOT ILIKE '%%Excluida%%';
                        """, (int(r["item_id"]),))
                        for (model_id,) in cur.fetchall():
                            # Preserva máquina/tempo/perda de quem já refinou na página 🏭
                            cur.execute("""
                                INSERT INTO map_engenharia_produto
                                    (model_id, id_material, peso_gramas, tempo_impressao_minutos, custo_embalagem, taxa_perda_percentual)
                                VALUES (%s, %s, %s, 0, %s, 0)
                                ON CONFLICT (model_id) DO UPDATE SET
                                    id_material = EXCLUDED.id_material,
                                    peso_gramas = EXCLUDED.peso_gramas,
                                    custo_embalagem = EXCLUDED.custo_embalagem,
                                    data_mapeamento = CURRENT_TIMESTAMP;
                            """, (model_id, id_por_nome[filamento], float(peso), float(r["Embalagem (R$)"] or 0)))
                        gravados += 1
            limpar_caches()
            st.success(
                f"✅ {gravados} produto(s) mapeado(s) (todas as variações). "
                + (f"{pulados} sem filamento/peso foram pulados. " if pulados else "")
                + "Veja a aba 💰 — o lucro já está recalculado."
            )

# ══════════════════════════════════════════════════════════════════════════════
# ABA 1 — LUCRO POR PRODUTO
# ══════════════════════════════════════════════════════════════════════════════

with aba_lucro:
    if st.button("🔄 Sincronizar vendas + catálogo agora (API)", type="primary"):
        with st.status("Sincronizando com a Shopee...", expanded=True) as status:
            res_cat = sincronizar_catalogo()
            st.write(f"Catálogo: {res_cat.get('produtos', 0)} produtos (fotos incluídas).")
            ultima = obter_ultima_sincronizacao("PEDIDOS")
            inicio = (ultima - timedelta(days=4)) if ultima else datetime(2026, 1, 26)
            agora = datetime.now()
            total = 0
            ultimo_ok = None
            for ini_b, fim_b in fatiar_periodo(inicio, agora):
                res = sincronizar_pedidos(ini_b, fim_b)
                if res.get("status") != "sucesso":
                    st.error(f"Falha no bloco {ini_b:%d/%m}–{fim_b:%d/%m}; rode de novo para continuar de onde parou.")
                    break
                total += res.get("registros", 0)
                ultimo_ok = fim_b
            if ultimo_ok:
                registrar_sincronizacao("PEDIDOS", inicio, ultimo_ok, "SUCESSO", total)
            res_detalhe = detalhar_repasses_pendentes()
            if res_detalhe["pendentes"]:
                st.write(f"Repasses antigos detalhados: {res_detalhe['detalhados']} de {res_detalhe['pendentes']}.")
            status.update(label=f"✅ Sincronizado: {total} pedidos processados.", state="complete")
        limpar_caches()

    try:
        dossie = carregar_dossie()
    except MigracaoPendenteError as e:
        st.error(str(e))
        dossie = []

    if not dossie:
        st.info("Sem dados ainda — use o botão de sincronização acima.")
    else:
        fotos = {it[0]: it[2] for it in carregar_mapeamento_itens()}

        por_item = {}
        for d in dossie:
            it = por_item.setdefault(d["item_id"], {
                "nome": d["nome_produto"], "vendas_7d": 0, "vendas_30d": 0,
                "lucro_7d": 0.0, "lucro_30d": 0.0, "custos": [], "variacoes": 0, "mapeadas": 0,
            })
            it["vendas_7d"] += d.get("vendas_7d_reais") or 0
            it["vendas_30d"] += d.get("vendas_30d_reais") or 0
            it["lucro_7d"] += d.get("lucro_liquido_real_7d") or 0
            it["lucro_30d"] += d.get("lucro_liquido_real_30d") or 0
            it["variacoes"] += 1
            if d.get("custo_fab_real"):
                it["mapeadas"] += 1
                it["custos"].append(d["custo_fab_real"])

        total_7d = sum(i["lucro_7d"] for i in por_item.values())
        total_30d = sum(i["lucro_30d"] for i in por_item.values())
        mapeados = sum(1 for i in por_item.values() if i["mapeadas"] >= i["variacoes"])

        c1, c2, c3 = st.columns(3)
        c1.metric("💰 Lucro líquido 7 dias", _fmt_moeda(total_7d))
        c2.metric("💰 Lucro líquido 30 dias", _fmt_moeda(total_30d))
        c3.metric("🧵 Produtos com custo mapeado", f"{mapeados}/{len(por_item)}")

        if mapeados < len(por_item):
            st.warning(
                f"⚠️ {len(por_item) - mapeados} produto(s) ainda sem custo de material — para eles o lucro "
                "abaixo ignora a fabricação (aparece ⚠️). Mapeie na aba 🧵 (leva ~2 minutos)."
            )
        st.caption(
            "Como o lucro é calculado: repasse da Shopee por pedido (rateado entre os itens do pedido; pedidos "
            "ainda não pagos usam a fração que o próprio produto costuma receber) + recarga de anúncios (não é "
            "custo, vira saldo) − custo de fabricação (material, máquina, embalagem e perda) − gasto real de "
            "anúncios. Abra a conta de qualquer produto na aba 🔍 Raio-X."
        )

        lucro7, lucro30 = st.tabs(["Últimos 7 dias", "Últimos 30 dias"])
        for aba_janela, sufixo, rotulo_janela in ((lucro7, "7d", "7 dias"), (lucro30, "30d", "30 dias")):
            with aba_janela:
                df_lucro = pd.DataFrame([
                    {
                        "Foto": fotos.get(iid),
                        "Produto": m["nome"][:60],
                        f"Vendas {rotulo_janela}": m[f"vendas_{sufixo}"],
                        f"Lucro {rotulo_janela}": round(m[f"lucro_{sufixo}"], 2),
                        "Custo/peça": (
                            _fmt_moeda(min(m["custos"])) if m["custos"] and min(m["custos"]) == max(m["custos"])
                            else f"{_fmt_moeda(min(m['custos']))}–{_fmt_moeda(max(m['custos']))}" if m["custos"] else "⚠️ não mapeado"
                        ),
                        "Lucro por unidade": (
                            round(m[f"lucro_{sufixo}"] / m[f"vendas_{sufixo}"], 2) if m[f"vendas_{sufixo}"] else None
                        ),
                    }
                    for iid, m in sorted(por_item.items(), key=lambda x: x[1][f"lucro_{sufixo}"], reverse=True)
                ])
                st.dataframe(
                    df_lucro, hide_index=True, use_container_width=True, height=600,
                    column_config={
                        "Foto": st.column_config.ImageColumn("Foto", width="small"),
                        f"Lucro {rotulo_janela}": st.column_config.NumberColumn(f"Lucro {rotulo_janela}", format=FORMATO_MOEDA),
                        "Lucro por unidade": st.column_config.NumberColumn("Lucro por unidade", format=FORMATO_MOEDA),
                    },
                )
        st.caption(
            "📌 Produto com vendas e lucro NEGATIVO = cada venda piora o resultado (taxa + fabricação acima do "
            "preço). Os mesmos números alimentam o plano de ação da 📊 Visão Central e o 🧠 Cérebro."
        )

# ══════════════════════════════════════════════════════════════════════════════
# ABA 2 — RAIO-X DO PRODUTO (a conta aberta)
# ══════════════════════════════════════════════════════════════════════════════

with aba_raio_x:
    try:
        produtos = carregar_produtos_vendidos()
    except Exception as exc:  # views da migração 19 ausentes
        st.error(f"Não consegui ler o financeiro por item. Rode `python init_db/aplicar_migrations.py`. Detalhe: {exc}")
        produtos = []

    if not produtos:
        st.info("Nenhuma venda nos últimos 12 meses. Sincronize na aba 💰.")
    else:
        opcoes = {f"{nome[:80]} · {int(unidades)} un. em 12 meses": (item_id, foto) for item_id, nome, foto, unidades in produtos}
        col_foto, col_produto, col_periodo = st.columns([1, 6, 3])
        escolha = col_produto.selectbox("Produto", list(opcoes))
        periodo = col_periodo.radio("Período", list(PERIODOS), horizontal=True, index=1)
        item_id, foto = opcoes[escolha]
        if foto:
            col_foto.image(foto, width=72)
        dias = PERIODOS[periodo]

        df = carregar_pedidos_do_produto(item_id, dias)
        custo = carregar_custo_do_produto(item_id)
        gasto_ads, ads_recentes = carregar_anuncios_do_produto(item_id, dias)

        # ── 1. Custo por peça ──────────────────────────────────────────────────
        secao(1, "Custo de fabricação por peça",
              "Uma peça só, sem nenhuma venda misturada. Vem da engenharia (página 🏭) e do preço do filamento (aba 🧵).")
        if custo.empty:
            st.warning("Este produto ainda não tem custo mapeado: o lucro abaixo ignora a fabricação. Mapeie na aba 🧵.")
        else:
            for _, cv in custo.iterrows():
                if len(custo) > 1:
                    st.markdown(f"**Variação: {cv['variacao']}**")
                if cv["unidade_material"] == "kg":
                    como_material = f"{cv['peso_gramas']:.1f} g de {cv['material']} × {_fmt_moeda(cv['preco_material'])}/kg"
                else:
                    como_material = f"{cv['peso_gramas']:.1f} g de {cv['material']} × {_fmt_moeda(cv['preco_material'])}/{cv['unidade_material']}"
                tempo = float(cv["tempo_impressao_minutos"] or 0)
                linhas_custo = [
                    ("Material", como_material, cv["custo_material"]),
                    ("Máquina (energia)",
                     f"{tempo:.0f} min ({tempo / 60:.1f} h) na {cv['maquina'] or 'máquina não informada'} × {_fmt_moeda(cv['custo_maquina_hora'])}/h",
                     cv["custo_maquina"]),
                    ("Embalagem", "Valor fixo por peça", cv["custo_embalagem"]),
                    ("Perda (refugo)", f"{cv['perda_percentual']:.0f}% sobre material + máquina + embalagem", cv["custo_perda"]),
                    ("= Custo por peça", "", cv["custo_total"]),
                ]
                st.dataframe(
                    pd.DataFrame([{"Parcela": a, "Como é calculado": b, "Valor": float(c or 0)} for a, b, c in linhas_custo]),
                    hide_index=True, use_container_width=True,
                    column_config={"Valor": st.column_config.NumberColumn("Valor", format=FORMATO_MOEDA)},
                )

        # ── 2. Para onde vai o dinheiro ────────────────────────────────────────
        secao(2, "Para onde vai o dinheiro de cada venda",
              f"Somando todas as vendas de {periodo.lower()}, direto dos repasses da Shopee. Por unidade = total ÷ unidades vendidas.")
        if df.empty:
            st.info("Nenhuma venda deste produto no período escolhido.")
        else:
            unidades = int(df["quantidade"].sum())
            linhas = linhas_para_onde_vai_o_dinheiro(df, gasto_ads, ads_recentes)
            valor_total = float(df["valor_item"].sum())
            lucro_total = linhas[-1][1]

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Unidades vendidas", unidades)
            m2.metric("Preço médio", _fmt_moeda(valor_total / unidades))
            m3.metric("Repasse por unidade", _fmt_moeda(float(df["repasse"].sum()) / unidades))
            m4.metric("Lucro por unidade", _fmt_moeda(lucro_total / unidades))

            tabela = pd.DataFrame([
                {
                    "Linha": nome,
                    "Total no período": total,
                    "Por unidade": total / unidades,
                    "% do preço": (total / valor_total * 100) if valor_total else 0.0,
                    "O que é": explicacao,
                }
                for nome, total, explicacao in linhas
                if abs(total) >= 0.005 or nome in LINHAS_SEMPRE_VISIVEIS
            ])
            st.dataframe(
                tabela, hide_index=True, use_container_width=True, height=(len(tabela) + 1) * 35 + 3,
                column_config={
                    "Total no período": st.column_config.NumberColumn(format=FORMATO_MOEDA),
                    "Por unidade": st.column_config.NumberColumn(format=FORMATO_MOEDA),
                    "% do preço": st.column_config.NumberColumn(format="%.1f%%"),
                },
            )

            pedidos_estimados = int((df["origem_repasse"] != "REAL").sum())
            devolucoes = int(df["houve_devolucao"].sum())
            avisos = []
            if pedidos_estimados:
                avisos.append(
                    f"{pedidos_estimados} item(ns) de pedido ainda não pago(s) pela Shopee entram com repasse "
                    "<b>estimado</b> pela fração que este produto costuma receber."
                )
            if devolucoes:
                avisos.append(f"{devolucoes} devolução(ões) no período: o repasse delas fica perto de zero, mas a peça foi fabricada.")
            if not df["custo_mapeado"].all():
                avisos.append("Há variação sem custo mapeado: a fabricação dela está como zero.")
            avisos.append(
                "A <b>recarga de anúncios</b> é um desconto automático do repasse que vira saldo de anúncios na Shopee. "
                "Por isso ela volta na conta e o anúncio é cobrado uma vez só, pelo gasto real. Se a recarga for bem "
                "maior que o gasto por muito tempo, sobra saldo parado: confira em Marketing › Anúncios Shopee."
            )
            nota("<br>".join(avisos), titulo="Como ler esta conta")

            # ── 3. Pedido a pedido ─────────────────────────────────────────────
            secao(3, "Pedido a pedido", "Cada linha é um item de pedido, com os mesmos números da conta acima.")
            por_pedido = pd.DataFrame({
                "Data": df["data"],
                "Pedido": df["order_sn"],
                "Status": df["status_pedido"],
                "Qtd": df["quantidade"],
                "Preço": df["valor_item"],
                "Comissão": df["comissao_shopee"],
                "Taxa serviço": df["taxa_servico"],
                "Afiliado": df["comissao_afiliado"],
                "Cupom loja": df["cupom_vendedor"],
                "Seguro frete": df["seguro_frete"],
                "Reembolso": df["reembolso_devolucao"],
                "Ajuste Shopee": df["ajuste_pos_venda"],
                "Recarga ads": df["recarga_ads"],
                "Repasse": df["repasse"],
                "Repasse é": df["origem_repasse"].map(lambda o: "✅ pago" if o == "REAL" else "⏳ estimado"),
                "Custo fabricação": df["custo_fabricacao"],
                "Lucro antes de ads": df["lucro_antes_ads"],
                "Devolução": df["houve_devolucao"].map(lambda x: "↩️ sim" if x else ""),
            })
            colunas_moeda = [
                "Preço", "Comissão", "Taxa serviço", "Afiliado", "Cupom loja", "Seguro frete", "Reembolso",
                "Ajuste Shopee", "Recarga ads", "Repasse", "Custo fabricação", "Lucro antes de ads",
            ]
            st.dataframe(
                por_pedido, hide_index=True, use_container_width=True,
                column_config={c: st.column_config.NumberColumn(c, format=FORMATO_MOEDA) for c in colunas_moeda},
            )
