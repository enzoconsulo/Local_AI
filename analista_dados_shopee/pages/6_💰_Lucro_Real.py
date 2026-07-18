"""
pages/6_💰_Lucro_Real.py
========================
A aba de LUCRO pedida pelo usuário: mapeamento de custo em 2 passos rápidos
(filamentos com preço do kg + peso por PRODUTO — uma linha por produto, a
mesma configuração vale para todas as variações) e o lucro calculado por
produto com 1 botão de sync da API.

Decisões de desenho:
  - Editar o preço do kg de um filamento (lote mais caro/barato) muda apenas
    o CÁLCULO de lucro — nunca o preço de venda na Shopee.
  - O mapeamento enxuto grava peso/filamento/embalagem em TODAS as variações
    do item (tempo de impressão, máquina e taxa de perda ficam para quem
    quiser refinar na página 🏭 — o upsert preserva o que já existir lá).
  - Lucro = repasse líquido REAL do escrow (rateado por item do pedido;
    quando o pedido ainda não liquidou, estimativa 80% − R$3) − custo de
    material − gasto de ads rateado. Tudo local, zero IA.
"""

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from utils.db_pool import get_connection
from workers.sync_catalogo import sincronizar_catalogo
from workers.sync_pedidos import sincronizar_pedidos
from workers.importar_planilhas import (
    obter_ultima_sincronizacao,
    registrar_sincronizacao,
    fatiar_periodo,
)
from cerebro.config import MigracaoPendenteError
from cerebro.dossie import gerar_dossie_produtos_com_memoria

st.set_page_config(page_title="Lucro Real", page_icon="💰", layout="wide")

from utils.ui import aplicar_estilo, cabecalho, secao
aplicar_estilo()
cabecalho(
    "💰", "Lucro Real por Produto",
    "Repasse do escrow − material − ads, 100% local. Mapeie os custos na 2ª aba (2 passos) e o lucro aparece aqui.",
)


def _fmt_moeda(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


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


def limpar_caches():
    carregar_materiais.clear()
    carregar_mapeamento_itens.clear()
    carregar_dossie.clear()


aba_lucro, aba_custos = st.tabs(["💰 Lucro por produto", "🧵 Mapear custos (2 passos)"])

# ══════════════════════════════════════════════════════════════════════════════
# ABA 2 — MAPEAMENTO RÁPIDO DE CUSTOS
# ══════════════════════════════════════════════════════════════════════════════

with aba_custos:
    secao(1, "Seus filamentos e o preço do quilo",
          "Pagou mais caro ou mais barato num lote? Edite o preço aqui — muda só o cálculo de lucro, nunca o preço de venda na Shopee.")

    materiais = carregar_materiais()
    df_mat = pd.DataFrame(
        [{"id": m[0], "Filamento": m[1], "Preço do kg (R$)": float(m[2]), "Estoque (kg)": float(m[3])} for m in materiais]
        or [{"id": None, "Filamento": "PLA Branco", "Preço do kg (R$)": 90.0, "Estoque (kg)": 1.0}]
    )
    edit_mat = st.data_editor(
        df_mat, num_rows="dynamic", hide_index=True, use_container_width=True,
        column_config={"id": None},  # oculto — controle interno
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
                "abaixo ignora o filamento (aparece ⚠️). Mapeie na aba 🧵 ao lado (leva ~2 minutos)."
            )
        st.caption(
            "Como o lucro é calculado: repasse líquido REAL do escrow por pedido (rateado entre os itens do "
            "pedido; pedidos ainda não liquidados usam a estimativa 80% do preço − R$ 3) − custo de material "
            "(peso × preço do kg + embalagem) − gasto de ads rateado por produto."
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
                        "Margem por unidade": (
                            f"{m[f'lucro_{sufixo}'] / m[f'vendas_{sufixo}']:.2f}/un." if m[f"vendas_{sufixo}"] else "—"
                        ),
                    }
                    for iid, m in sorted(por_item.items(), key=lambda x: x[1][f"lucro_{sufixo}"], reverse=True)
                ])
                st.dataframe(
                    df_lucro, hide_index=True, use_container_width=True, height=600,
                    column_config={
                        "Foto": st.column_config.ImageColumn("Foto", width="small"),
                        f"Lucro {rotulo_janela}": st.column_config.NumberColumn(f"Lucro {rotulo_janela}", format="R$ %.2f"),
                    },
                )
        st.caption(
            "📌 Produto com vendas e lucro NEGATIVO = cada venda piora o resultado (taxa + material acima do "
            "preço). Os mesmos números alimentam o plano de ação da 📊 Visão Central e o 🧠 Cérebro."
        )
