"""
pages/5_🧵_Mapeamento_Insumos.py
=================================
Importa o backup JSON do app local de controle de gastos (filamentos +
produtos + histórico de vendas/estoque) e propõe automaticamente o vínculo
com o Data Warehouse da Shopee:

    dim_materiais            <- filaments (agrupados por tipo+cor)
    dim_maquinas              <- distintos valores de energy_h
    map_engenharia_produto    <- products (peso, tempo, embalagem) vinculado
                                  ao model_id certo via fuzzy match de nome

Nada é gravado no banco sem revisão manual do usuário na tela.
"""

import difflib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
import psycopg2.extras
import streamlit as st
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))
load_dotenv(ROOT_DIR / "CHAVES_DADOS.env", override=True)

from utils.db_pool import get_connection

st.set_page_config(page_title="Mapeamento de Insumos", page_icon="🧵", layout="wide")

# ==============================================================================
# SEÇÃO 1 — LEITURA E NORMALIZAÇÃO DO BACKUP
# ==============================================================================

def carregar_backup_json(uploaded_file) -> dict:
    return json.loads(uploaded_file.getvalue().decode("utf-8"))


def normalizar_texto(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", txt or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", " ", txt.lower()).strip()


def score_similaridade(a: str, b: str) -> float:
    """Combina ratio de caracteres + interseção de palavras. 0 a 1."""
    na, nb = normalizar_texto(a), normalizar_texto(b)
    if not na or not nb:
        return 0.0
    ratio = difflib.SequenceMatcher(None, na, nb).ratio()
    set_a, set_b = set(na.split()), set(nb.split())
    jaccard = len(set_a & set_b) / len(set_a | set_b) if (set_a | set_b) else 0.0
    contido = 0.9 if (na in nb or nb in na) and len(na) > 3 else 0.0
    return round(max(ratio, jaccard, contido), 3)


def montar_lookup_filamentos(backup: dict) -> dict:
    """id do filamento -> {type, color}. Inclui filamentos já consumidos,
    resgatados via snapshot histórico do impStock (rolos que já sumiram
    da lista atual mas ainda aparecem em vendas/estoque antigos)."""
    lookup = {}
    for f in backup.get("filaments", []):
        lookup[f["id"]] = {"type": f["type"], "color": f["color"]}
    for s in backup.get("impStock", []):
        snap = (s.get("snapshot") or {}).get("filamentSnapshot")
        if snap and snap.get("id") and snap["id"] not in lookup:
            lookup[snap["id"]] = {"type": snap["type"], "color": snap["color"]}
    return lookup


def extrair_materiais_backup(backup: dict) -> list[dict]:
    """Agrupa filamentos por (tipo, cor) e calcula custo médio por KG
    (a dim_materiais do seu DW guarda custo em R$/kg)."""
    grupos = defaultdict(lambda: {"pesos": [], "custos_kg": []})
    for f in backup.get("filaments", []):
        chave = (f["type"].strip(), f["color"].strip())
        custo_kg = (f["price"] / f["initialWeight"]) * 1000 if f["initialWeight"] else 0
        grupos[chave]["pesos"].append(f["weight"])
        grupos[chave]["custos_kg"].append(custo_kg)

    materiais = []
    for (tipo, cor), dados in grupos.items():
        custo_medio_kg = sum(dados["custos_kg"]) / len(dados["custos_kg"])
        estoque_kg = sum(dados["pesos"]) / 1000
        materiais.append({
            "nome_sugerido": f"{cor} {tipo.upper()}",
            "tipo": tipo,
            "custo_por_unidade": round(custo_medio_kg, 4),
            "unidade_medida": "kg",
            "estoque_atual": round(estoque_kg, 3),
        })
    return materiais


def extrair_maquinas_backup(backup: dict) -> list[float]:
    """Valores distintos de energy_h (R$/hora) encontrados nos produtos."""
    valores = sorted({
        round(float(p["energy_h"]), 4)
        for p in backup.get("products", [])
        if p.get("energy_h")
    })
    return valores


def determinar_material_por_produto_e_variante(backup: dict, lookup_fil: dict):
    """
    Retorna:
      material_padrao: {productId: (tipo, cor)}      -> uso mais frequente
      overrides:       {(productId, variant_label_lower): (tipo, cor)}
    baseado no histórico real de impStock + impSales.
    """
    contagem_produto = defaultdict(Counter)
    for registro in backup.get("impStock", []) + backup.get("impSales", []):
        fid, pid = registro.get("filamentId"), registro.get("productId")
        if fid in lookup_fil and pid:
            tipo_cor = (lookup_fil[fid]["type"], lookup_fil[fid]["color"])
            contagem_produto[pid][tipo_cor] += registro.get("qty", 1)

    material_padrao = {pid: c.most_common(1)[0][0] for pid, c in contagem_produto.items()}

    overrides = {}
    for s in backup.get("impStock", []):
        fid, pid = s.get("filamentId"), s.get("productId")
        vlabel = (s.get("variantLabel") or "").strip().lower()
        if fid in lookup_fil and pid and vlabel and vlabel != "padrão":
            overrides[(pid, vlabel)] = (lookup_fil[fid]["type"], lookup_fil[fid]["color"])

    return material_padrao, overrides


def montar_itens_engenharia(backup: dict) -> list[dict]:
    """Uma linha por (produto local, variante) com os dados de engenharia
    e o material sugerido já resolvido em nome legível."""
    lookup_fil = montar_lookup_filamentos(backup)
    material_padrao, overrides = determinar_material_por_produto_e_variante(backup, lookup_fil)

    itens = []
    for p in backup.get("products", []):
        pid = p["id"]
        variantes = p.get("variants") or [{"id": "default", "label": "Padrão"}]
        for v in variantes:
            vlabel = v.get("label", "Padrão")
            vlabel_lower = vlabel.strip().lower()
            material = overrides.get((pid, vlabel_lower)) or material_padrao.get(pid)
            nome_material_sugerido = f"{material[1]} {material[0].upper()}" if material else None
            itens.append({
                "produto_id_local": pid,
                "nome_produto_local": p["name"],
                "variante_label": vlabel,
                "peso_gramas": p.get("fil_g", 0),
                "tempo_impressao_minutos": round(float(p.get("hours", 0)) * 60),
                "custo_embalagem": p.get("pack", 0),
                "energy_h": round(float(p.get("energy_h", 0)), 4),
                "nome_material_sugerido": nome_material_sugerido,
            })
    return itens


# ==============================================================================
# SEÇÃO 2 — LEITURA DO DATA WAREHOUSE (SÓ LEITURA)
# ==============================================================================

@st.cache_data(ttl=120)
def buscar_produtos_dw() -> pd.DataFrame:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("""
                SELECT p.item_id, p.nome_atual, v.model_id, v.nome_variacao
                FROM dim_produtos p
                JOIN dim_variacoes v ON p.item_id = v.item_id
            """)
            linhas = cur.fetchall()
    return pd.DataFrame([dict(r) for r in linhas])


@st.cache_data(ttl=60)
def buscar_materiais_dw() -> pd.DataFrame:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("""
                SELECT id_material, nome, tipo, custo_por_unidade, unidade_medida, estoque_atual
                FROM dim_materiais ORDER BY nome
            """)
            linhas = cur.fetchall()
    return pd.DataFrame([dict(r) for r in linhas])


@st.cache_data(ttl=60)
def buscar_maquinas_dw() -> pd.DataFrame:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("""
                SELECT id_maquina, nome_modelo, custo_energia_hora, status
                FROM dim_maquinas ORDER BY nome_modelo
            """)
            linhas = cur.fetchall()
    return pd.DataFrame([dict(r) for r in linhas])


def melhor_match_produto(nome_local: str, df_produtos: pd.DataFrame):
    """Retorna (item_id, nome_atual, score) do melhor match, ou (None, None, 0)."""
    if df_produtos.empty:
        return None, None, 0.0
    candidatos = df_produtos[["item_id", "nome_atual"]].drop_duplicates()
    melhor = (None, None, 0.0)
    for _, row in candidatos.iterrows():
        s = score_similaridade(nome_local, row["nome_atual"])
        if s > melhor[2]:
            melhor = (row["item_id"], row["nome_atual"], s)
    return melhor


def melhor_match_variacao(variante_label: str, item_id, df_produtos: pd.DataFrame):
    """Dado um item_id já escolhido, acha o model_id cuja nome_variacao mais
    se parece com o label local. Se só existir uma variação, usa direto."""
    subset = df_produtos[df_produtos["item_id"] == item_id]
    if subset.empty:
        return None, None
    if len(subset) == 1:
        row = subset.iloc[0]
        return row["model_id"], row["nome_variacao"]
    melhor = (None, None, -1.0)
    for _, row in subset.iterrows():
        s = score_similaridade(variante_label, row["nome_variacao"] or "")
        if s > melhor[2]:
            melhor = (row["model_id"], row["nome_variacao"], s)
    return melhor[0], melhor[1]


# ==============================================================================
# SEÇÃO 3 — GRAVAÇÃO (SELECT-then-INSERT/UPDATE, sem depender de UNIQUE/PK)
# ==============================================================================

def obter_ou_criar_material(cur, id_material_existente, nome, tipo, custo_por_unidade,
                             unidade_medida, estoque_atual, sincronizar_estoque: bool) -> int:
    if id_material_existente:
        if sincronizar_estoque:
            cur.execute("""
                UPDATE dim_materiais
                SET custo_por_unidade = %s, unidade_medida = %s,
                    estoque_atual = %s, data_atualizacao = NOW()
                WHERE id_material = %s
            """, (custo_por_unidade, unidade_medida, estoque_atual, id_material_existente))
        else:
            cur.execute("""
                UPDATE dim_materiais
                SET custo_por_unidade = %s, unidade_medida = %s, data_atualizacao = NOW()
                WHERE id_material = %s
            """, (custo_por_unidade, unidade_medida, id_material_existente))
        return id_material_existente

    cur.execute("""
        INSERT INTO dim_materiais (nome, tipo, custo_por_unidade, unidade_medida, estoque_atual, data_atualizacao)
        VALUES (%s, %s, %s, %s, %s, NOW())
        RETURNING id_material
    """, (nome, tipo, custo_por_unidade, unidade_medida, estoque_atual))
    return cur.fetchone()[0]


def obter_ou_criar_maquina(cur, id_maquina_existente, novo_nome, custo_energia_hora) -> int:
    if id_maquina_existente:
        return id_maquina_existente
    cur.execute("""
        INSERT INTO dim_maquinas (nome_modelo, custo_energia_hora, status)
        VALUES (%s, %s, 'Ativa')
        RETURNING id_maquina
    """, (novo_nome, custo_energia_hora))
    return cur.fetchone()[0]


def salvar_engenharia(cur, model_id, id_material, id_maquina, peso_gramas,
                       tempo_impressao_minutos, custo_embalagem, taxa_perda_percentual=0):
    cur.execute("SELECT id_mapeamento FROM map_engenharia_produto WHERE model_id = %s", (model_id,))
    row = cur.fetchone()
    if row:
        cur.execute("""
            UPDATE map_engenharia_produto
            SET id_material = %s, id_maquina = %s, peso_gramas = %s,
                tempo_impressao_minutos = %s, custo_embalagem = %s,
                taxa_perda_percentual = %s, data_mapeamento = NOW()
            WHERE id_mapeamento = %s
        """, (id_material, id_maquina, peso_gramas, tempo_impressao_minutos,
              custo_embalagem, taxa_perda_percentual, row[0]))
    else:
        cur.execute("""
            INSERT INTO map_engenharia_produto
                (model_id, id_material, id_maquina, peso_gramas,
                 tempo_impressao_minutos, custo_embalagem, taxa_perda_percentual, data_mapeamento)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        """, (model_id, id_material, id_maquina, peso_gramas,
              tempo_impressao_minutos, custo_embalagem, taxa_perda_percentual))


# ==============================================================================
# SEÇÃO 4 — INTERFACE
# ==============================================================================

st.title("🧵 Mapeamento de Insumos (Filamentos & Engenharia)")
st.markdown(
    "Importe o backup do seu app local de controle de gastos para vincular "
    "automaticamente **materiais**, **máquina** e **engenharia de produto** "
    "(peso, tempo de impressão, embalagem) ao Data Warehouse da Shopee. "
    "Nada é gravado até você revisar e clicar em **Aplicar Mapeamento**."
)

arquivo_backup = st.file_uploader("📂 Backup JSON do controle de gastos", type=["json"])

if not arquivo_backup:
    st.info("Envie o arquivo de backup para começar.")
    st.stop()

if "backup_carregado_nome" not in st.session_state or st.session_state.backup_carregado_nome != arquivo_backup.name:
    backup = carregar_backup_json(arquivo_backup)
    st.session_state.backup_dados = backup
    st.session_state.backup_carregado_nome = arquivo_backup.name
    st.session_state.materiais_backup = extrair_materiais_backup(backup)
    st.session_state.maquinas_backup = extrair_maquinas_backup(backup)
    st.session_state.itens_engenharia = montar_itens_engenharia(backup)

df_produtos_dw = buscar_produtos_dw()
df_materiais_dw = buscar_materiais_dw()
df_maquinas_dw = buscar_maquinas_dw()

if df_produtos_dw.empty:
    st.warning("Nenhum produto encontrado em dim_produtos/dim_variacoes. Rode a Sincronização primeiro.")
    st.stop()

st.divider()

# ── 1. Materiais ──────────────────────────────────────────────────────────────
st.subheader("1️⃣ Materiais (Filamentos)")
sincronizar_estoque = st.checkbox(
    "🔁 Sincronizar também o estoque atual (sobrescreve o estoque_atual dos materiais já existentes)",
    value=False,
)

opcoes_materiais_existentes = {"— Criar novo material —": None}
for _, r in df_materiais_dw.iterrows():
    opcoes_materiais_existentes[f"{r['nome']} (R$ {r['custo_por_unidade']:.2f}/{r['unidade_medida']})"] = r["id_material"]

decisoes_materiais = {}  # nome_sugerido -> {"id_existente":..., "dados": {...}}
for i, mat in enumerate(st.session_state.materiais_backup):
    # tenta achar automaticamente um material existente com nome parecido
    melhor_nome, melhor_score = None, 0.0
    for _, r in df_materiais_dw.iterrows():
        s = score_similaridade(mat["nome_sugerido"], r["nome"])
        if s > melhor_score:
            melhor_score, melhor_nome = s, r["nome"]
    label_default = "— Criar novo material —"
    if melhor_score >= 0.6:
        for label in opcoes_materiais_existentes:
            if label.startswith(melhor_nome):
                label_default = label
                break

    col1, col2, col3 = st.columns([2, 2, 2])
    with col1:
        st.markdown(f"**{mat['nome_sugerido']}**")
        st.caption(f"R$ {mat['custo_por_unidade']:.2f}/kg · estoque backup: {mat['estoque_atual']:.2f} kg")
    with col2:
        escolha = st.selectbox(
            "Vincular a", list(opcoes_materiais_existentes.keys()),
            index=list(opcoes_materiais_existentes.keys()).index(label_default),
            key=f"mat_escolha_{i}", label_visibility="collapsed",
        )
    with col3:
        if melhor_score > 0 and melhor_score < 0.6:
            st.caption(f"parecido: {melhor_nome} ({melhor_score:.0%})")

    decisoes_materiais[mat["nome_sugerido"]] = {
        "id_existente": opcoes_materiais_existentes[escolha],
        "dados": mat,
    }

st.divider()

# ── 2. Máquina ────────────────────────────────────────────────────────────────
st.subheader("2️⃣ Máquina (custo de energia/hora)")
opcoes_maquinas_existentes = {"— Criar nova máquina —": None}
for _, r in df_maquinas_dw.iterrows():
    opcoes_maquinas_existentes[f"{r['nome_modelo']} (R$ {r['custo_energia_hora']:.4f}/h)"] = r["id_maquina"]

decisoes_maquinas = {}  # energy_h -> {"id_existente":..., "novo_nome":...}
for i, valor in enumerate(st.session_state.maquinas_backup):
    melhor_label, menor_dif = "— Criar nova máquina —", None
    for _, r in df_maquinas_dw.iterrows():
        dif = abs(float(r["custo_energia_hora"]) - valor)
        if menor_dif is None or dif < menor_dif:
            menor_dif = dif
            melhor_label = f"{r['nome_modelo']} (R$ {r['custo_energia_hora']:.4f}/h)"

    col1, col2, col3 = st.columns([2, 2, 2])
    with col1:
        st.markdown(f"**Custo detectado: R$ {valor:.4f}/h**")
        st.caption(f"Usado em {sum(1 for p in st.session_state.backup_dados.get('products', []) if round(float(p.get('energy_h',0)),4)==valor)} produto(s)")
    with col2:
        escolha = st.selectbox(
            "Vincular a", list(opcoes_maquinas_existentes.keys()),
            index=list(opcoes_maquinas_existentes.keys()).index(melhor_label) if menor_dif is not None and menor_dif < 0.001 else 0,
            key=f"maq_escolha_{i}", label_visibility="collapsed",
        )
    with col3:
        novo_nome = ""
        if opcoes_maquinas_existentes[escolha] is None:
            novo_nome = st.text_input("Nome da nova máquina", value=f"Impressora ({valor:.2f} R$/h)",
                                       key=f"maq_nome_{i}", label_visibility="collapsed")

    decisoes_maquinas[valor] = {"id_existente": opcoes_maquinas_existentes[escolha], "novo_nome": novo_nome}

st.divider()

# ── 3. Produtos / Engenharia ────────────────────────────────────────────────
st.subheader("3️⃣ Produtos → Engenharia (vínculo com item_id / model_id da Shopee)")

LIMIAR_ALTA_CONFIANCA = 0.70   # ✅ mapeia automático, você só revisa
LIMIAR_MEDIA_CONFIANCA = 0.40  # 🟡 precisa da sua confirmação explícita
# abaixo de 0.40 → 🔴 sem sugestão confiável, seleção manual obrigatória

lista_produtos_dw = [
    f"{row['nome_atual']} (item {row['item_id']})"
    for _, row in df_produtos_dw[["item_id", "nome_atual"]].drop_duplicates().iterrows()
]
mapa_label_para_item_id = {}
for _, row in df_produtos_dw[["item_id", "nome_atual"]].drop_duplicates().iterrows():
    mapa_label_para_item_id[f"{row['nome_atual']} (item {row['item_id']})"] = row["item_id"]

# Pré-calcula o match de todos os itens uma única vez, e classifica em 3 grupos
if "matches_calculados" not in st.session_state or st.session_state.get("matches_calculados_para") != st.session_state.backup_carregado_nome:
    matches = []
    for i, item in enumerate(st.session_state.itens_engenharia):
        item_id_sugerido, nome_sugerido, score = melhor_match_produto(item["nome_produto_local"], df_produtos_dw)
        matches.append({"idx": i, "item_id_sugerido": item_id_sugerido, "nome_sugerido": nome_sugerido, "score": score})
    st.session_state.matches_calculados = matches
    st.session_state.matches_calculados_para = st.session_state.backup_carregado_nome

matches = st.session_state.matches_calculados
grupo_alta = [m for m in matches if m["score"] >= LIMIAR_ALTA_CONFIANCA]
grupo_media = [m for m in matches if LIMIAR_MEDIA_CONFIANCA <= m["score"] < LIMIAR_ALTA_CONFIANCA]
grupo_baixa = [m for m in matches if m["score"] < LIMIAR_MEDIA_CONFIANCA]

m1, m2, m3 = st.columns(3)
m1.metric("✅ Mapeados automaticamente", len(grupo_alta))
m2.metric("🟡 Pendentes de confirmação", len(grupo_media))
m3.metric("🔴 Sem sugestão confiável", len(grupo_baixa))

if grupo_media:
    st.warning(
        f"⚠️ **{len(grupo_media)} produto(s)** têm um nome parecido mas não idêntico ao cadastrado na Shopee — "
        "confirme se é o mesmo produto antes de aplicar, na seção 🟡 abaixo."
    )
    if st.button("✅ Confirmar todas as sugestões pendentes (🟡)", key="confirmar_lote_pendentes"):
        for m in grupo_media:
            st.session_state[f"incluir_{m['idx']}"] = True
        st.rerun()

decisoes_engenharia = []  # lista de dicts prontos pra salvar


def renderizar_item_engenharia(m, incluir_padrao: bool, exigir_selecao_manual: bool = False):
    """Renderiza o card/expander de um item e devolve seu resultado se marcado."""
    i = m["idx"]
    item = st.session_state.itens_engenharia[i]
    item_id_sugerido, nome_sugerido, score = m["item_id_sugerido"], m["nome_sugerido"], m["score"]
    label_sugerido = f"{nome_sugerido} (item {item_id_sugerido})" if item_id_sugerido else None
    icone = "🟢" if score >= LIMIAR_ALTA_CONFIANCA else "🟡" if score >= LIMIAR_MEDIA_CONFIANCA else "🔴"

    titulo = f"{icone} {item['nome_produto_local']} — {item['variante_label']}"
    titulo += f"  →  {nome_sugerido} ({score:.0%})" if label_sugerido else "  →  sem sugestão"

    with st.expander(titulo, expanded=exigir_selecao_manual):
        col1, col2 = st.columns(2)
        with col1:
            # Itens sem confiança suficiente NÃO vêm pré-preenchidos — força escolha manual
            index_default = 0
            if not exigir_selecao_manual and label_sugerido in lista_produtos_dw:
                index_default = lista_produtos_dw.index(label_sugerido) + 1
            escolha_produto = st.selectbox(
                "Produto Shopee correspondente",
                ["— Ignorar este item —"] + lista_produtos_dw,
                index=index_default,
                key=f"prod_escolha_{i}",
            )
        item_id_escolhido = mapa_label_para_item_id.get(escolha_produto)

        model_id_escolhido = None
        if item_id_escolhido is not None:
            subset_var = df_produtos_dw[df_produtos_dw["item_id"] == item_id_escolhido]
            opcoes_variacao = {
                f"{r['nome_variacao']} (model {r['model_id']})": r["model_id"]
                for _, r in subset_var.iterrows()
            }
            model_sugerido, _ = melhor_match_variacao(item["variante_label"], item_id_escolhido, df_produtos_dw)
            label_var_sugerida = next((label for label, mid in opcoes_variacao.items() if mid == model_sugerido), None)
            with col2:
                escolha_variacao = st.selectbox(
                    "Variação correspondente",
                    list(opcoes_variacao.keys()),
                    index=list(opcoes_variacao.keys()).index(label_var_sugerida) if label_var_sugerida else 0,
                    key=f"var_escolha_{i}",
                )
            model_id_escolhido = opcoes_variacao[escolha_variacao]

        st.caption(
            f"⚖️ {item['peso_gramas']} g · ⏱️ {item['tempo_impressao_minutos']} min · "
            f"📦 R$ {item['custo_embalagem']:.2f} embalagem · ⚡ R$ {item['energy_h']:.4f}/h"
        )

        if item["nome_material_sugerido"] and decisoes_materiais.get(item["nome_material_sugerido"]):
            st.caption(f"🧵 Material sugerido: **{item['nome_material_sugerido']}**")
        else:
            st.caption("🧵 Nenhum material identificado no histórico — selecione manualmente:")

        opcoes_material_manual = {"— Nenhum (definir depois) —": (None, None)}
        for nome_sug, dec in decisoes_materiais.items():
            opcoes_material_manual[nome_sug] = (nome_sug, dec)
        default_material_label = (
            item["nome_material_sugerido"]
            if item["nome_material_sugerido"] in opcoes_material_manual
            else "— Nenhum (definir depois) —"
        )
        escolha_material = st.selectbox(
            "Material a gravar", list(opcoes_material_manual.keys()),
            index=list(opcoes_material_manual.keys()).index(default_material_label),
            key=f"item_material_{i}",
        )

        rotulo_check = (
            "✅ Confirmo que é o mesmo produto — incluir no mapeamento"
            if exigir_selecao_manual or score < LIMIAR_ALTA_CONFIANCA
            else "✅ Incluir este item no mapeamento"
        )
        incluir = st.checkbox(rotulo_check, value=incluir_padrao, key=f"incluir_{i}")

    if incluir and model_id_escolhido is not None:
        return {
            "model_id": model_id_escolhido,
            "peso_gramas": item["peso_gramas"],
            "tempo_impressao_minutos": item["tempo_impressao_minutos"],
            "custo_embalagem": item["custo_embalagem"],
            "energy_h": item["energy_h"],
            "nome_material_escolhido": opcoes_material_manual[escolha_material][0],
        }
    return None


if grupo_alta:
    st.markdown(f"##### ✅ Alta confiança — mapeados automaticamente ({len(grupo_alta)})")
    st.caption("Nome bate bem com o produto da Shopee. Revise se quiser, mas já vêm marcados para gravar.")
    for m in grupo_alta:
        resultado = renderizar_item_engenharia(m, incluir_padrao=True, exigir_selecao_manual=False)
        if resultado:
            decisoes_engenharia.append(resultado)

if grupo_media:
    st.markdown(f"##### 🟡 Pendente de confirmação ({len(grupo_media)})")
    st.caption("Nome parecido, mas não idêntico — confirme se é o mesmo produto antes de incluir.")
    for m in grupo_media:
        resultado = renderizar_item_engenharia(m, incluir_padrao=False, exigir_selecao_manual=False)
        if resultado:
            decisoes_engenharia.append(resultado)

if grupo_baixa:
    st.markdown(f"##### 🔴 Sem sugestão confiável — selecione manualmente ({len(grupo_baixa)})")
    st.caption("Não encontramos um nome parecido na Shopee. Escolha o produto certo ou deixe como 'Ignorar'.")
    for m in grupo_baixa:
        resultado = renderizar_item_engenharia(m, incluir_padrao=False, exigir_selecao_manual=True)
        if resultado:
            decisoes_engenharia.append(resultado)

st.divider()
st.markdown(f"**{len(decisoes_engenharia)}** de **{len(st.session_state.itens_engenharia)}** itens serão gravados.")

# ==============================================================================
# SEÇÃO 5 — APLICAR
# ==============================================================================

if st.button("🚀 Aplicar Mapeamento", type="primary", use_container_width=True, disabled=not decisoes_engenharia):
    with st.status("Gravando mapeamento no Data Warehouse...", expanded=True) as status:
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    # 1. materiais
                    ids_materiais_gravados = {}
                    for nome_sug, dec in decisoes_materiais.items():
                        m = dec["dados"]
                        id_mat = obter_ou_criar_material(
                            cur, dec["id_existente"], nome_sug, m["tipo"],
                            m["custo_por_unidade"], m["unidade_medida"], m["estoque_atual"],
                            sincronizar_estoque,
                        )
                        ids_materiais_gravados[nome_sug] = id_mat
                    st.write(f"✅ {len(ids_materiais_gravados)} materiais processados.")

                    # 2. máquinas
                    ids_maquinas_gravadas = {}
                    for valor, dec in decisoes_maquinas.items():
                        id_maq = obter_ou_criar_maquina(cur, dec["id_existente"], dec["novo_nome"], valor)
                        ids_maquinas_gravadas[valor] = id_maq
                    st.write(f"✅ {len(ids_maquinas_gravadas)} máquinas processadas.")

                    # 3. engenharia
                    for item in decisoes_engenharia:
                        id_material = ids_materiais_gravados.get(item["nome_material_escolhido"])
                        id_maquina = ids_maquinas_gravadas.get(item["energy_h"])
                        salvar_engenharia(
                            cur, item["model_id"], id_material, id_maquina,
                            item["peso_gramas"], item["tempo_impressao_minutos"],
                            item["custo_embalagem"],
                        )
                    st.write(f"✅ {len(decisoes_engenharia)} vínculos de engenharia gravados.")

                conn.commit()
            status.update(label="Mapeamento aplicado com sucesso!", state="complete")
            st.cache_data.clear()
            st.balloons()
        except Exception as e:
            status.update(label="Falha ao aplicar mapeamento", state="error")
            st.error(f"Erro: {e}")