import streamlit as st
import psycopg2
import psycopg2.errors
import pandas as pd
import os
from dotenv import load_dotenv
from pathlib import Path

# Carrega as variáveis do CHAVES_DADOS.env
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=ROOT_DIR / "CHAVES_DADOS.env")

st.set_page_config(page_title="Engenharia de Fábrica", page_icon="⚙️", layout="wide")

# ==============================================================================
# CONEXÃO BLINDADA COM O POSTGRESQL (Abre e fecha a cada requisição)
# ==============================================================================
def get_db_connection():
    try:
        return psycopg2.connect(
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT"),
            database=os.getenv("POSTGRES_DB"),
            user=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD")
        )
    except Exception as e:
        st.error(f"🚨 Falha ao conectar no PostgreSQL. Verifique se o Docker está rodando. Erro: {e}")
        st.stop()


def run_query(query, params=None):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            if cur.description:
                col_names = [desc[0] for desc in cur.description]
                return pd.DataFrame(cur.fetchall(), columns=col_names)
            return pd.DataFrame()


def run_insert(query, params):
    """Executa INSERT/UPDATE. Retorna True/False e mostra erro cru se falhar."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
            conn.commit()
        return True
    except Exception as e:
        st.error(f"Erro de Banco de Dados: {e}")
        return False


def run_delete(query, params):
    """Executa DELETE. Retorna (sucesso, mensagem_de_erro_amigavel_ou_None)."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
            conn.commit()
        return True, None
    except psycopg2.errors.ForeignKeyViolation:
        return False, (
            "Este item está em uso em pelo menos um mapeamento de produto. "
            "Altere o mapeamento para outro material/máquina antes de excluir este."
        )
    except Exception as e:
        return False, str(e)


# ==============================================================================
# VISUAL — CSS, cores e badges
# ==============================================================================
st.markdown("""
<style>
.eng-card {
    border: 1px solid rgba(148,163,184,0.25);
    border-radius: 14px;
    padding: 14px 16px;
    margin-bottom: 10px;
    background: rgba(255,255,255,0.02);
}
.eng-card.ok { border-left: 4px solid #22c55e; }
.eng-card.pending { border-left: 4px solid #f59e0b; }
.eng-card.danger { border-left: 4px solid #ef4444; }
.eng-badge {
    display:inline-block; padding: 2px 10px; border-radius: 999px;
    font-size: 0.72rem; font-weight:600; white-space:nowrap;
}
.eng-badge.green  { background: rgba(34,197,94,0.15);  color:#22c55e; }
.eng-badge.orange { background: rgba(245,158,11,0.15); color:#f59e0b; }
.eng-badge.red    { background: rgba(239,68,68,0.15);  color:#ef4444; }
.eng-badge.gray   { background: rgba(148,163,184,0.15);color:#94a3b8; }
.eng-badge.blue   { background: rgba(59,130,246,0.15); color:#3b82f6; }
.eng-dot {
    display:inline-block; width:14px; height:14px; border-radius:50%;
    margin-right:6px; vertical-align:middle; border:1px solid rgba(255,255,255,0.3);
}
.eng-row { display:flex; justify-content:space-between; align-items:center; }
.eng-muted { font-size:0.78rem; color:#94a3b8; }
.eng-sticky-summary {
    border: 1px solid rgba(34,197,94,0.35);
    background: rgba(34,197,94,0.06);
    border-radius: 14px;
    padding: 12px 16px;
    margin-bottom: 16px;
}
</style>
""", unsafe_allow_html=True)

CORES_CONHECIDAS = {
    "branco": "#f8fafc", "preto": "#0f172a", "cinza": "#94a3b8", "rosa": "#f472b6",
    "vermelho": "#ef4444", "azul": "#3b82f6", "verde": "#22c55e", "amarelo": "#eab308",
    "laranja": "#f97316", "roxo": "#a855f7", "dourado": "#ca8a04", "prata": "#cbd5e1",
    "transparente": "#e2e8f0", "marrom": "#92400e", "bege": "#d6c7a1",
}

TIPOS_MATERIAL = ["Filamento", "Resina", "Embalagem", "Outro"]
UNIDADES_MATERIAL = ["kg", "unidade", "litro"]
MODO_ESTOQUE_REAL = "📦 Tenho controle de estoque real (sei o peso/quantidade atual)"
MODO_CUSTO_FIXO = "🎯 Só uma base de custo média (sem estoque — ex: histórico antigo, preço médio de mercado)"


def cor_hex_do_nome(nome: str) -> str:
    nome_l = (nome or "").lower()
    for cor, hexv in CORES_CONHECIDAS.items():
        if cor in nome_l:
            return hexv
    return "#64748b"


def badge(texto: str, cor: str) -> str:
    return f'<span class="eng-badge {cor}">{texto}</span>'


# ==============================================================================
# INTERFACE — CABEÇALHO + PAINEL DE STATUS GERAL
# ==============================================================================
st.title("⚙️ Engenharia de Fábrica e Insumos")
st.markdown("Alimente os custos de materiais, energia e perdas (refugo). A IA usará isso para auditar a sua operação de forma cirúrgica.")

df_mat = run_query("""
    SELECT id_material, nome, tipo, custo_por_unidade, unidade_medida, estoque_atual
    FROM dim_materiais ORDER BY nome
""")
df_maq = run_query("""
    SELECT id_maquina, nome_modelo, custo_energia_hora, status
    FROM dim_maquinas ORDER BY nome_modelo
""")
df_status_geral = run_query("""
    SELECT p.item_id, p.nome_atual, v.model_id, v.nome_variacao,
           (m.model_id IS NOT NULL) AS mapeado,
           m.id_material, m.id_maquina,
           m.peso_gramas, m.tempo_impressao_minutos, m.custo_embalagem, m.taxa_perda_percentual
    FROM dim_produtos p
    JOIN dim_variacoes v ON v.item_id = p.item_id
    LEFT JOIN map_engenharia_produto m ON m.model_id = v.model_id
    WHERE p.status_shopee = 'NORMAL'
    ORDER BY p.nome_atual, v.nome_variacao
""")

total_variacoes = len(df_status_geral)
mapeadas = int(df_status_geral["mapeado"].sum()) if not df_status_geral.empty else 0
pendentes = total_variacoes - mapeadas

c1, c2, c3, c4 = st.columns(4)
c1.metric("🧵 Materiais cadastrados", len(df_mat))
c2.metric("🖨️ Máquinas cadastradas", len(df_maq))
c3.metric("📦 Variações ativas", total_variacoes)
c4.metric("✅ Custo mapeado", f"{mapeadas}/{total_variacoes}" if total_variacoes else "0/0",
          delta=f"{pendentes} pendente(s)" if pendentes else "tudo em dia",
          delta_color="inverse" if pendentes else "normal")

if total_variacoes == 0:
    st.info("Nenhuma variação ativa encontrada. Rode a Sincronização do Catálogo primeiro.")
elif pendentes > 0:
    st.error(
        f"⚠️ **{pendentes} variação(ões)** ainda sem custo de fabricação mapeado — "
        f"a IA **não consegue calcular o lucro real** delas até isso ser preenchido."
    )
    with st.expander(f"🔍 Ver quais faltam mapear ({pendentes})", expanded=False):
        faltantes = df_status_geral[~df_status_geral["mapeado"]]
        for nome_produto, grupo in faltantes.groupby("nome_atual"):
            st.markdown(f"**{nome_produto}**")
            for _, row in grupo.iterrows():
                st.markdown(f"&nbsp;&nbsp;&nbsp;⬜ {row['nome_variacao']}", unsafe_allow_html=True)
else:
    st.success("✅ Todas as variações ativas já têm custo de fabricação mapeado.")

st.divider()

tab_materiais, tab_maquinas, tab_mapeamento = st.tabs(["🛒 Filamentos & Embalagens", "🖨️ Máquinas 3D", "🔗 Mapeamento de Peças"])

# ==============================================================================
# ABA 1 — MATERIAIS (cards visuais + editar/excluir inline + modo custo fixo)
# ==============================================================================
with tab_materiais:
    col1, col2 = st.columns([1, 2])

    with col1:
        st.subheader("Cadastrar Novo Insumo")
        with st.form("form_material", clear_on_submit=True):
            nome = st.text_input("Nome (Ex: PETG Preto Fosco)")
            tipo = st.selectbox("Tipo de Insumo", TIPOS_MATERIAL)

            modo_custo = st.radio(
                "Como você quer registrar o custo deste material?",
                [MODO_ESTOQUE_REAL, MODO_CUSTO_FIXO],
                help=(
                    "No modo 'base de custo média', o valor serve só como multiplicador do peso "
                    "do produto no cálculo de custo — não é decrementado e não gera alertas de "
                    "estoque baixo, já que você não está rastreando a quantidade física real."
                ),
            )
            rastreia_estoque = modo_custo == MODO_ESTOQUE_REAL

            custo = st.number_input(
                "Preço médio por unidade (Ex: preço de 1KG) - R$" if not rastreia_estoque else "Custo do Lote Fechado (Ex: Preço de 1KG) - R$",
                min_value=0.0, format="%.2f",
            )
            unidade = st.selectbox("Unidade Base", UNIDADES_MATERIAL)

            estoque = None
            if rastreia_estoque:
                estoque = st.number_input(
                    "Estoque Físico Atual (na medida escolhida)", min_value=0.0, format="%.2f",
                    help="A IA usará isso para prever rupturas logísticas."
                )
            else:
                st.caption("♾️ Este material não terá estoque rastreado — servirá apenas como base de cálculo.")

            if st.form_submit_button("💾 Salvar Material", use_container_width=True):
                if nome:
                    query = """INSERT INTO dim_materiais (nome, tipo, custo_por_unidade, unidade_medida, estoque_atual)
                               VALUES (%s, %s, %s, %s, %s)"""
                    if run_insert(query, (nome, tipo, custo, unidade, estoque)):
                        st.success(f"Material '{nome}' cadastrado com sucesso!")
                        st.rerun()
                else:
                    st.warning("O nome não pode estar vazio.")

    with col2:
        st.subheader("Estoque de Insumos Atual")
        busca_mat = st.text_input("🔎 Buscar material", key="busca_mat", placeholder="Ex: PETG, Branco...")

        df_mat_filtrado = df_mat
        if busca_mat:
            df_mat_filtrado = df_mat[df_mat["nome"].str.contains(busca_mat, case=False, na=False)]

        if df_mat_filtrado.empty:
            st.info("Nenhum material encontrado.")
        else:
            for _, row in df_mat_filtrado.reset_index(drop=True).iterrows():
                id_mat = int(row["id_material"])
                cor_hex = cor_hex_do_nome(row["nome"])
                rastreia = pd.notna(row["estoque_atual"])
                estoque_valor = float(row["estoque_atual"]) if rastreia else None

                if rastreia:
                    estoque_baixo = estoque_valor < 1.0  # ajuste o limiar conforme sua realidade
                    card_classe = "danger" if estoque_baixo else "ok"
                    badge_html = badge("⚠️ Estoque baixo", "red") if estoque_baixo else badge("✅ Em estoque", "green")
                    linha_estoque = f"<span>📦 {estoque_valor:.2f} {row['unidade_medida']}</span>"
                else:
                    card_classe = ""
                    badge_html = badge("🎯 Custo fixo (sem estoque)", "blue")
                    linha_estoque = "<span>♾️ multiplicador de peso, sem estoque</span>"

                with st.container(border=True):
                    editando = st.session_state.get("editando_material") == id_mat
                    confirmando_excl = st.session_state.get("excluindo_material") == id_mat

                    if editando:
                        st.markdown(f"**✏️ Editando: {row['nome']}**")
                        ec1, ec2 = st.columns(2)
                        with ec1:
                            novo_nome = st.text_input("Nome", value=row["nome"], key=f"edit_mat_nome_{id_mat}")
                            novo_tipo = st.selectbox(
                                "Tipo", TIPOS_MATERIAL,
                                index=TIPOS_MATERIAL.index(row["tipo"]) if row["tipo"] in TIPOS_MATERIAL else 0,
                                key=f"edit_mat_tipo_{id_mat}",
                            )
                        with ec2:
                            novo_custo = st.number_input("Custo por unidade (R$)", min_value=0.0, value=float(row["custo_por_unidade"]), format="%.2f", key=f"edit_mat_custo_{id_mat}")
                            nova_unidade = st.selectbox(
                                "Unidade", UNIDADES_MATERIAL,
                                index=UNIDADES_MATERIAL.index(row["unidade_medida"]) if row["unidade_medida"] in UNIDADES_MATERIAL else 0,
                                key=f"edit_mat_unidade_{id_mat}",
                            )
                        novo_modo = st.radio(
                            "Modo de custo", [MODO_ESTOQUE_REAL, MODO_CUSTO_FIXO],
                            index=0 if rastreia else 1,
                            key=f"edit_mat_modo_{id_mat}",
                        )
                        novo_rastreia = novo_modo == MODO_ESTOQUE_REAL
                        novo_estoque = None
                        if novo_rastreia:
                            novo_estoque = st.number_input(
                                "Estoque atual", min_value=0.0,
                                value=estoque_valor if rastreia else 0.0, format="%.2f",
                                key=f"edit_mat_estoque_{id_mat}",
                            )
                        else:
                            st.caption("♾️ Sem estoque rastreado — apenas base de custo.")

                        bs1, bs2 = st.columns(2)
                        if bs1.button("💾 Salvar", key=f"salvar_mat_{id_mat}", type="primary", use_container_width=True):
                            ok = run_insert(
                                """UPDATE dim_materiais SET nome=%s, tipo=%s, custo_por_unidade=%s,
                                   unidade_medida=%s, estoque_atual=%s WHERE id_material=%s""",
                                (novo_nome, novo_tipo, novo_custo, nova_unidade, novo_estoque, id_mat),
                            )
                            if ok:
                                st.session_state.editando_material = None
                                st.success("Material atualizado!")
                                st.rerun()
                        if bs2.button("Cancelar", key=f"cancelar_mat_{id_mat}", use_container_width=True):
                            st.session_state.editando_material = None
                            st.rerun()

                    elif confirmando_excl:
                        st.warning(f"Tem certeza que deseja excluir **{row['nome']}**? Essa ação não pode ser desfeita.")
                        bc1, bc2 = st.columns(2)
                        if bc1.button("🗑️ Confirmar exclusão", key=f"confirma_excl_mat_{id_mat}", type="primary", use_container_width=True):
                            ok, erro = run_delete("DELETE FROM dim_materiais WHERE id_material=%s", (id_mat,))
                            st.session_state.excluindo_material = None
                            if ok:
                                st.success("Material excluído!")
                                st.rerun()
                            else:
                                st.error(erro)
                        if bc2.button("Cancelar", key=f"cancela_excl_mat_{id_mat}", use_container_width=True):
                            st.session_state.excluindo_material = None
                            st.rerun()

                    else:
                        st.markdown(f"""
                        <div class="eng-card {card_classe}" style="margin-bottom:8px;">
                            <div class="eng-row">
                                <div>
                                    <span class="eng-dot" style="background:{cor_hex};"></span>
                                    <strong>{row['nome']}</strong>
                                    <div class="eng-muted">{row['tipo']}</div>
                                </div>
                                {badge_html}
                            </div>
                            <div class="eng-row" style="margin-top:10px; font-size:0.85rem;">
                                <span>💰 R$ {row['custo_por_unidade']:.2f}/{row['unidade_medida']}</span>
                                {linha_estoque}
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                        be1, be2 = st.columns(2)
                        if be1.button("✏️ Editar", key=f"btn_editar_mat_{id_mat}", use_container_width=True):
                            st.session_state.editando_material = id_mat
                            st.rerun()
                        if be2.button("🗑️ Excluir", key=f"btn_excluir_mat_{id_mat}", use_container_width=True):
                            st.session_state.excluindo_material = id_mat
                            st.rerun()

# ==============================================================================
# ABA 2 — MÁQUINAS (cards visuais + editar/excluir inline)
# ==============================================================================
with tab_maquinas:
    col1, col2 = st.columns([1, 2])

    with col1:
        st.subheader("Cadastrar Impressora")
        with st.form("form_maquina", clear_on_submit=True):
            nome_maq = st.text_input("Modelo da Máquina (Ex: Bambu Lab P1P)")
            custo_kwh = st.number_input(
                "Custo de Energia por Hora (R$/h)", min_value=0.0, format="%.4f",
                help="Calcule o consumo (kW) * Tarifa da concessionária (R$/kWh)"
            )

            if st.form_submit_button("💾 Salvar Impressora", use_container_width=True):
                if nome_maq:
                    if run_insert("INSERT INTO dim_maquinas (nome_modelo, custo_energia_hora) VALUES (%s, %s)", (nome_maq, custo_kwh)):
                        st.success(f"Máquina '{nome_maq}' salva!")
                        st.rerun()
                else:
                    st.warning("O nome não pode estar vazio.")

    with col2:
        st.subheader("Frota Ativa")
        if df_maq.empty:
            st.info("Nenhuma máquina cadastrada ainda.")
        else:
            for _, row in df_maq.reset_index(drop=True).iterrows():
                id_maq = int(row["id_maquina"])
                ativa = str(row["status"] or "").strip().lower() == "ativa"
                badge_html = badge("🟢 Ativa", "green") if ativa else badge("⚪ Inativa", "gray")

                with st.container(border=True):
                    editando = st.session_state.get("editando_maquina") == id_maq
                    confirmando_excl = st.session_state.get("excluindo_maquina") == id_maq

                    if editando:
                        st.markdown(f"**✏️ Editando: {row['nome_modelo']}**")
                        novo_nome = st.text_input("Modelo", value=row["nome_modelo"], key=f"edit_maq_nome_{id_maq}")
                        novo_custo = st.number_input("Custo de energia (R$/h)", min_value=0.0, value=float(row["custo_energia_hora"]), format="%.4f", key=f"edit_maq_custo_{id_maq}")
                        novo_status = st.selectbox(
                            "Status", ["Ativa", "Inativa"],
                            index=0 if ativa else 1,
                            key=f"edit_maq_status_{id_maq}",
                        )
                        bs1, bs2 = st.columns(2)
                        if bs1.button("💾 Salvar", key=f"salvar_maq_{id_maq}", type="primary", use_container_width=True):
                            ok = run_insert(
                                "UPDATE dim_maquinas SET nome_modelo=%s, custo_energia_hora=%s, status=%s WHERE id_maquina=%s",
                                (novo_nome, novo_custo, novo_status, id_maq),
                            )
                            if ok:
                                st.session_state.editando_maquina = None
                                st.success("Máquina atualizada!")
                                st.rerun()
                        if bs2.button("Cancelar", key=f"cancelar_maq_{id_maq}", use_container_width=True):
                            st.session_state.editando_maquina = None
                            st.rerun()

                    elif confirmando_excl:
                        st.warning(f"Tem certeza que deseja excluir **{row['nome_modelo']}**? Essa ação não pode ser desfeita.")
                        bc1, bc2 = st.columns(2)
                        if bc1.button("🗑️ Confirmar exclusão", key=f"confirma_excl_maq_{id_maq}", type="primary", use_container_width=True):
                            ok, erro = run_delete("DELETE FROM dim_maquinas WHERE id_maquina=%s", (id_maq,))
                            st.session_state.excluindo_maquina = None
                            if ok:
                                st.success("Máquina excluída!")
                                st.rerun()
                            else:
                                st.error(erro)
                        if bc2.button("Cancelar", key=f"cancela_excl_maq_{id_maq}", use_container_width=True):
                            st.session_state.excluindo_maquina = None
                            st.rerun()

                    else:
                        st.markdown(f"""
                        <div class="eng-card {'ok' if ativa else ''}" style="margin-bottom:8px;">
                            <div class="eng-row">
                                <div>
                                    🖨️ <strong>{row['nome_modelo']}</strong>
                                    <div class="eng-muted">R$ {row['custo_energia_hora']:.4f} por hora de impressão</div>
                                </div>
                                {badge_html}
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                        be1, be2 = st.columns(2)
                        if be1.button("✏️ Editar", key=f"btn_editar_maq_{id_maq}", use_container_width=True):
                            st.session_state.editando_maquina = id_maq
                            st.rerun()
                        if be2.button("🗑️ Excluir", key=f"btn_excluir_maq_{id_maq}", use_container_width=True):
                            st.session_state.excluindo_maquina = id_maq
                            st.rerun()

# ==============================================================================
# ABA 3 — MAPEAMENTO (grade colapsável + modo individual OU lote)
# ==============================================================================
MODO_INDIVIDUAL = "🎯 Uma variação por vez (valores individuais)"
MODO_LOTE = "📋 Aplicar em lote (mesmos valores p/ várias)"

UPSERT_ENGENHARIA_SQL = """
    INSERT INTO map_engenharia_produto
    (model_id, id_material, id_maquina, peso_gramas, tempo_impressao_minutos, custo_embalagem, taxa_perda_percentual)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (model_id) DO UPDATE SET
        id_material = EXCLUDED.id_material,
        id_maquina = EXCLUDED.id_maquina,
        peso_gramas = EXCLUDED.peso_gramas,
        tempo_impressao_minutos = EXCLUDED.tempo_impressao_minutos,
        custo_embalagem = EXCLUDED.custo_embalagem,
        taxa_perda_percentual = EXCLUDED.taxa_perda_percentual;
"""

with tab_mapeamento:
    st.subheader("🔗 Vínculo Produtivo: Shopee ↔ Fábrica")

    if df_status_geral.empty or df_mat.empty or df_maq.empty:
        st.warning("⚠️ Você precisa de cadastrar pelo menos 1 Material, 1 Máquina e Sincronizar o Catálogo da Shopee antes de fazer o mapeamento.")
    else:
        if "eng_grid_aberta" not in st.session_state:
            st.session_state.eng_grid_aberta = True

        resumo_produtos = (
            df_status_geral.groupby(["item_id", "nome_atual"])["mapeado"]
            .agg(mapeadas="sum", total="count")
            .reset_index()
        )

        item_id_sel = st.session_state.get("eng_produto_sel")
        if item_id_sel is None and not resumo_produtos.empty:
            item_id_sel = int(resumo_produtos.iloc[0]["item_id"])
            st.session_state.eng_produto_sel = item_id_sel

        # ---- Barra compacta do produto selecionado (sempre visível, sem precisar rolar) ----
        if item_id_sel is not None and not st.session_state.eng_grid_aberta:
            prod_resumo = resumo_produtos[resumo_produtos["item_id"] == item_id_sel].iloc[0]
            sc1, sc2 = st.columns([5, 1])
            with sc1:
                st.markdown(f"""
                <div class="eng-sticky-summary">
                    📦 <strong>Produto atual: {prod_resumo['nome_atual']}</strong>
                    &nbsp;&nbsp;{badge(f"{int(prod_resumo['mapeadas'])}/{int(prod_resumo['total'])} mapeadas", "green" if prod_resumo['mapeadas'] == prod_resumo['total'] else "orange")}
                </div>
                """, unsafe_allow_html=True)
            with sc2:
                if st.button("🔁 Trocar produto", key="trocar_produto_topo", use_container_width=True):
                    st.session_state.eng_grid_aberta = True
                    st.rerun()

        # ---- Passo 1: grade de produtos (só aparece se aberta) ----
        if st.session_state.eng_grid_aberta:
            st.markdown("#### 1️⃣ Escolha o produto")
            busca_prod = st.text_input("🔎 Buscar produto", placeholder="Ex: Porta-chaves, Suporte...", key="busca_prod_map")

            resumo_filtrado = resumo_produtos
            if busca_prod:
                resumo_filtrado = resumo_produtos[resumo_produtos["nome_atual"].str.contains(busca_prod, case=False, na=False)]

            if resumo_filtrado.empty:
                st.info("Nenhum produto encontrado com esse termo.")
            else:
                n_colunas = 3
                linhas = [resumo_filtrado.iloc[i:i + n_colunas] for i in range(0, len(resumo_filtrado), n_colunas)]
                for linha in linhas:
                    cols = st.columns(n_colunas)
                    for col, (_, prod) in zip(cols, linha.iterrows()):
                        pid = int(prod["item_id"])
                        completo = prod["mapeadas"] == prod["total"]
                        selecionado = item_id_sel == pid
                        with col:
                            with st.container(border=True):
                                st.markdown(f"📦 **{prod['nome_atual']}**")
                                st.progress(
                                    prod["mapeadas"] / prod["total"] if prod["total"] else 0,
                                    text=f"{int(prod['mapeadas'])}/{int(prod['total'])} variações mapeadas",
                                )
                                if selecionado:
                                    st.markdown(badge("✅ Produto atual", "green"), unsafe_allow_html=True)
                                    st.button("Selecionado", key=f"sel_prod_{pid}", disabled=True, use_container_width=True)
                                else:
                                    if completo:
                                        st.markdown(badge("Tudo certo", "gray"), unsafe_allow_html=True)
                                    else:
                                        st.markdown(badge("Pendências", "orange"), unsafe_allow_html=True)
                                    if st.button("➡️ Selecionar este", key=f"sel_prod_{pid}", type="primary", use_container_width=True):
                                        st.session_state.eng_produto_sel = pid
                                        st.session_state.eng_grid_aberta = False
                                        st.rerun()

            st.divider()

        # ---- Passo 2: mapear variações do produto selecionado ----
        if item_id_sel is not None:
            nome_produto_sel = df_status_geral.loc[df_status_geral["item_id"] == item_id_sel, "nome_atual"].iloc[0]
            variacoes_produto = df_status_geral[df_status_geral["item_id"] == item_id_sel].reset_index(drop=True)

            st.markdown(f"#### 2️⃣ Mapear variações de **{nome_produto_sel}**")

            if "modo_mapeamento" not in st.session_state:
                st.session_state.modo_mapeamento = MODO_INDIVIDUAL
            modo_mapeamento = st.radio(
                "Como deseja mapear?", [MODO_INDIVIDUAL, MODO_LOTE],
                key="modo_mapeamento", horizontal=True,
            )

            # ============================================================
            # MODO INDIVIDUAL — uma variação por vez, com valores próprios
            # ============================================================
            if modo_mapeamento == MODO_INDIVIDUAL:
                opcoes_variacao_ind = {
                    f"{'✅' if bool(row['mapeado']) else '⬜'} {row['nome_variacao']}": int(row["model_id"])
                    for _, row in variacoes_produto.iterrows()
                }
                label_var_escolhida = st.selectbox(
                    "Variação a editar", list(opcoes_variacao_ind.keys()), key="select_variacao_individual"
                )
                model_id_individual = opcoes_variacao_ind[label_var_escolhida]
                linha_atual = variacoes_produto[variacoes_produto["model_id"] == model_id_individual].iloc[0]
                ja_mapeado = bool(linha_atual["mapeado"])

                # --- INÍCIO DA MELHORIA: VISÃO GERAL DAS VARIAÇÕES ---
                st.markdown("###### 👁️ Comparativo: Todas as Variações deste Produto")
                n_colunas_vg = 3
                linhas_vg = [variacoes_produto.iloc[i:i + n_colunas_vg] for i in range(0, len(variacoes_produto), n_colunas_vg)]
                for linha_vg in linhas_vg:
                    cols_vg = st.columns(n_colunas_vg)
                    for col_vg, (_, var_vg) in zip(cols_vg, linha_vg.iterrows()):
                        with col_vg:
                            is_sel = (var_vg["model_id"] == model_id_individual)
                            borda_cor = "border: 2px solid #3b82f6;" if is_sel else ""
                            fundo_cor = "background: rgba(59,130,246,0.05);" if is_sel else ""
                            
                            mapeado_vg = bool(var_vg["mapeado"])
                            badge_vg = badge("✅ Mapeado", "green") if mapeado_vg else badge("⬜ Pendente", "orange")
                            
                            nome_mat_vg = df_mat.loc[df_mat['id_material'] == var_vg['id_material'], 'nome'].iloc[0] if mapeado_vg and pd.notna(var_vg['id_material']) and not df_mat[df_mat['id_material'] == var_vg['id_material']].empty else "Material pendente"
                            nome_maq_vg = df_maq.loc[df_maq['id_maquina'] == var_vg['id_maquina'], 'nome_modelo'].iloc[0] if mapeado_vg and pd.notna(var_vg['id_maquina']) and not df_maq[df_maq['id_maquina'] == var_vg['id_maquina']].empty else "Máquina pendente"

                            info_extra = f"""
                            <span style="color: #64748b;">🧵 {nome_mat_vg}</span><br>
                            <span style="color: #64748b;">🖨️ {nome_maq_vg}</span><br>
                            ⚖️ {var_vg['peso_gramas']:.0f}g · ⏱️ {int(var_vg['tempo_impressao_minutos'])}min<br>
                            🗑️ {var_vg['taxa_perda_percentual'] or 0:.0f}% refugo · 📦 R$ {var_vg['custo_embalagem'] or 0:.2f}
                            """ if mapeado_vg else "<span style='color: #ef4444;'>Nenhum dado cadastrado.</span>"
                            
                            st.markdown(f"""
                            <div class="eng-card {'ok' if mapeado_vg else 'pending'}" style="{borda_cor} {fundo_cor} padding: 10px; font-size: 0.82rem; margin-bottom: 5px;">
                                <div style="margin-bottom: 5px;"><strong>{var_vg['nome_variacao']}</strong> {badge_vg}</div>
                                <div style="line-height: 1.5;">{info_extra}</div>
                            </div>
                            """, unsafe_allow_html=True)
                st.write("") # Espaçamento
                # --- FIM DA VISÃO GERAL ---

                st.caption(
                    "✏️ Editando mapeamento existente — valores atuais já carregados abaixo."
                    if ja_mapeado else
                    "🆕 Esta variação ainda não tem custo mapeado — preencha os valores abaixo."
                )

                with st.form("form_map_individual", clear_on_submit=False):
                    col_mat, col_maq = st.columns(2)
                    with col_mat:
                        opcoes_mat = [f"{r['nome']} [{r['unidade_medida']}] — R$ {r['custo_por_unidade']:.2f}" for _, r in df_mat.iterrows()]
                        idx_mat = 0
                        if ja_mapeado and pd.notna(linha_atual["id_material"]):
                            ids_mat = df_mat["id_material"].tolist()
                            if int(linha_atual["id_material"]) in ids_mat:
                                idx_mat = ids_mat.index(int(linha_atual["id_material"]))
                        sel_mat_label = st.radio("Material usado", opcoes_mat, index=idx_mat, key=f"radio_mat_ind_{model_id_individual}")
                        id_material_sel = int(df_mat.iloc[opcoes_mat.index(sel_mat_label)]["id_material"])
                    with col_maq:
                        opcoes_maq = [f"🖨️ {r['nome_modelo']} — R$ {r['custo_energia_hora']:.4f}/h" for _, r in df_maq.iterrows()]
                        idx_maq = 0
                        if ja_mapeado and pd.notna(linha_atual["id_maquina"]):
                            ids_maq = df_maq["id_maquina"].tolist()
                            if int(linha_atual["id_maquina"]) in ids_maq:
                                idx_maq = ids_maq.index(int(linha_atual["id_maquina"]))
                        sel_maq_label = st.radio("Máquina que imprime", opcoes_maq, index=idx_maq, key=f"radio_maq_ind_{model_id_individual}")
                        id_maquina_sel = int(df_maq.iloc[opcoes_maq.index(sel_maq_label)]["id_maquina"])

                    col_a, col_b = st.columns(2)
                    with col_a:
                        peso = st.number_input(
                            "⚖️ Peso líquido (gramas)", min_value=0.0,
                            value=float(linha_atual["peso_gramas"]) if ja_mapeado and pd.notna(linha_atual["peso_gramas"]) else 50.0,
                            format="%.1f",
                            key=f"peso_ind_{model_id_individual}"
                        )
                        tempo = st.number_input(
                            "⏱️ Tempo de impressão (minutos)", min_value=0,
                            value=int(linha_atual["tempo_impressao_minutos"]) if ja_mapeado and pd.notna(linha_atual["tempo_impressao_minutos"]) else 60,
                            key=f"tempo_ind_{model_id_individual}"
                        )
                    with col_b:
                        custo_emb = st.number_input(
                            "📦 Custo de embalagem (R$)", min_value=0.0,
                            value=float(linha_atual["custo_embalagem"]) if ja_mapeado and pd.notna(linha_atual["custo_embalagem"]) else 1.50,
                            format="%.2f",
                            key=f"custo_emb_ind_{model_id_individual}"
                        )
                        perda = st.number_input(
                            "🗑️ Taxa de perda / refugo (%)", min_value=0.0, max_value=100.0,
                            value=float(linha_atual["taxa_perda_percentual"]) if ja_mapeado and pd.notna(linha_atual["taxa_perda_percentual"]) else 5.0,
                            format="%.1f",
                            key=f"perda_ind_{model_id_individual}"
                        )

                    if st.form_submit_button("💾 Salvar esta variação", type="primary", use_container_width=True):
                        if run_insert(UPSERT_ENGENHARIA_SQL, (
                            model_id_individual, id_material_sel, id_maquina_sel, peso, tempo, custo_emb, perda,
                        )):
                            st.success(f"Variação '{linha_atual['nome_variacao']}' mapeada com sucesso!")
                            st.rerun()

            # ============================================================
            # MODO LOTE — mesmos valores aplicados a várias variações
            # ============================================================
            else:
                st.caption("Marque as variações que devem receber exatamente o mesmo custo de fabricação abaixo.")
                with st.form("form_map_lote", clear_on_submit=False):
                    variacoes_marcadas = {}
                    n_colunas_var = 3
                    linhas_var = [variacoes_produto.iloc[i:i + n_colunas_var] for i in range(0, len(variacoes_produto), n_colunas_var)]
                    for linha in linhas_var:
                        cols = st.columns(n_colunas_var)
                        for col, (_, var) in zip(cols, linha.iterrows()):
                            with col:
                                with st.container(border=True):
                                    mapeado = bool(var["mapeado"])
                                    badge_html = badge("✅ Mapeado", "green") if mapeado else badge("⬜ Pendente", "orange")
                                    st.markdown(f"**{var['nome_variacao']}** \n{badge_html}", unsafe_allow_html=True)
                                    if mapeado:
                                        st.caption(
                                            f"Atual: {var['peso_gramas']:.0f}g · "
                                            f"{int(var['tempo_impressao_minutos'])}min · "
                                            f"{var['taxa_perda_percentual'] or 0:.0f}% refugo"
                                        )
                                    variacoes_marcadas[int(var["model_id"])] = st.checkbox(
                                        "Incluir neste lote", value=True, key=f"var_chip_{var['model_id']}"
                                    )

                    st.markdown("###### Material e máquina")
                    col_mat, col_maq = st.columns(2)
                    with col_mat:
                        opcoes_mat = [f"{r['nome']} [{r['unidade_medida']}] — R$ {r['custo_por_unidade']:.2f}" for _, r in df_mat.iterrows()]
                        sel_mat_label = st.radio("Material usado", opcoes_mat, key="radio_mat_lote")
                        id_material_sel = int(df_mat.iloc[opcoes_mat.index(sel_mat_label)]["id_material"])
                    with col_maq:
                        opcoes_maq = [f"🖨️ {r['nome_modelo']} — R$ {r['custo_energia_hora']:.4f}/h" for _, r in df_maq.iterrows()]
                        sel_maq_label = st.radio("Máquina que imprime", opcoes_maq, key="radio_maq_lote")
                        id_maquina_sel = int(df_maq.iloc[opcoes_maq.index(sel_maq_label)]["id_maquina"])

                    st.markdown("###### Dados de fabricação (aplicados a todas as marcadas)")
                    col_a, col_b = st.columns(2)
                    with col_a:
                        peso = st.number_input("⚖️ Peso líquido da peça (gramas)", min_value=0.0, value=50.0, format="%.1f")
                        tempo = st.number_input("⏱️ Tempo médio de impressão (minutos)", min_value=0, value=60)
                    with col_b:
                        custo_emb = st.number_input("📦 Custo fixo de embalagem (R$)", min_value=0.0, value=1.50, format="%.2f")
                        perda = st.number_input("🗑️ Taxa de perda / refugo esperado (%)", min_value=0.0, max_value=100.0, value=5.0, format="%.1f")

                    n_selecionadas = sum(1 for v in variacoes_marcadas.values() if v)
                    rotulo_botao = f"🔗 Salvar Mapeamento para {n_selecionadas} variação(ões)" if n_selecionadas else "🔗 Salvar Mapeamento"

                    if st.form_submit_button(rotulo_botao, type="primary", use_container_width=True):
                        model_ids_alvo = [mid for mid, marcado in variacoes_marcadas.items() if marcado]
                        if not model_ids_alvo:
                            st.warning("Selecione ao menos uma variação.")
                        else:
                            try:
                                with get_db_connection() as conn:
                                    with conn.cursor() as cur:
                                        for model_id in model_ids_alvo:
                                            cur.execute(UPSERT_ENGENHARIA_SQL, (
                                                model_id, id_material_sel, id_maquina_sel,
                                                peso, tempo, custo_emb, perda,
                                            ))
                                conn.commit()
                                st.success(f"Custo mapeado para {len(model_ids_alvo)} variação(ões) de {nome_produto_sel}!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erro de Banco de Dados: {e}")

        st.divider()

        # ---- Lista consolidada, agrupada por produto, com atalho de edição ----
        st.markdown("#### 📋 Mapeamentos já cadastrados")
        busca_lista = st.text_input("🔎 Buscar na lista de mapeados", key="busca_lista_map", placeholder="Ex: nome do produto...")

        df_mapeados_geral = df_status_geral[df_status_geral["mapeado"]]
        if busca_lista:
            df_mapeados_geral = df_mapeados_geral[df_mapeados_geral["nome_atual"].str.contains(busca_lista, case=False, na=False)]

        if df_mapeados_geral.empty:
            st.info("Nenhum mapeamento encontrado.")
        else:
            for nome_produto, grupo in df_mapeados_geral.groupby("nome_atual"):
                with st.expander(f"📦 {nome_produto} ({len(grupo)} variação(ões))"):
                    for _, row in grupo.iterrows():
                        refugo = row["taxa_perda_percentual"] or 0
                        cor_refugo = "red" if refugo > 10 else ("orange" if refugo > 5 else "green")
                        colx, coly = st.columns([5, 1])
                        with colx:
                            st.markdown(
                                f"""<div class="eng-card ok">
                                    <div class="eng-row">
                                        <strong>{row['nome_variacao']}</strong>
                                        {badge(f"{refugo:.0f}% refugo", cor_refugo)}
                                    </div>
                                    <div class="eng-muted" style="margin-top:6px;">
                                        ⚖️ {row['peso_gramas']:.0f}g · ⏱️ {int(row['tempo_impressao_minutos'])}min
                                    </div>
                                </div>""",
                                unsafe_allow_html=True,
                            )
                        with coly:
                            if st.button("✏️ Editar", key=f"editar_var_{row['model_id']}", use_container_width=True):
                                st.session_state.eng_produto_sel = int(row["item_id"])
                                st.session_state.eng_grid_aberta = False
                                st.session_state.modo_mapeamento = MODO_INDIVIDUAL
                                st.session_state.select_variacao_individual = f"✅ {row['nome_variacao']}"
                                st.rerun()