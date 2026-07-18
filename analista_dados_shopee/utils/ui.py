"""
utils/ui.py
===========
Design system do Estúdio Shopee DW — visual único, limpo e "app profissional"
(inspiração Apple: superfícies brancas sobre fundo #F5F5F7, cantos generosos,
sombras suaves, tipografia do sistema com tracking apertado).

Uso em TODA página, logo após o st.set_page_config:

    from utils.ui import aplicar_estilo, cabecalho, secao
    aplicar_estilo()
    cabecalho("📊", "Título da página", "Uma frase do que ela faz.")
    ...
    secao(1, "Nome da seção", "Explicação curta e didática.")
"""

import streamlit as st

_CSS = """
<style>
/* ── Tipografia do sistema (SF no Mac, Segoe no Windows) ──────────────────── */
/* NUNCA usar o seletor universal (*) aqui: os ícones do Streamlit são a fonte
   "Material Symbols" via ligadura de texto — sobrescrever a fonte deles faz o
   NOME do ícone (ex.: "keyboard_arrow_right", "upload") aparecer como texto
   cru dentro de botões, expanders e uploaders. Código (code/pre) também
   precisa manter a fonte mono. */
html, body,
[data-testid="stAppViewContainer"] *:not([data-testid="stIconMaterial"]):not([class*="material-symbols"]):not(code):not(pre):not(kbd):not(samp):not(code *):not(pre *) {
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display",
                 "Segoe UI Variable", "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
h1, h2, h3 { letter-spacing: -0.02em; font-weight: 700 !important; color: #1D1D1F; }
[data-testid="stCaptionContainer"], .stCaption { color: #6E6E73 !important; }

/* ── Área principal ───────────────────────────────────────────────────────── */
.block-container { padding-top: 2.4rem; padding-bottom: 4rem; }
hr { border: none; border-top: 1px solid rgba(0,0,0,.07); margin: 2rem 0; }

/* ── Cartões de métrica (st.metric) ───────────────────────────────────────── */
[data-testid="stMetric"] {
    background: #FFFFFF;
    border: 1px solid rgba(0,0,0,.06);
    border-radius: 16px;
    padding: 14px 16px;
    box-shadow: 0 1px 2px rgba(0,0,0,.04);
}
[data-testid="stMetricLabel"] p { font-weight: 600; color: #6E6E73; font-size: .82rem; }
/* clamp evita o valor truncar em "R$ 2..." quando há 6 cartões lado a lado */
[data-testid="stMetricValue"] {
    font-weight: 700; letter-spacing: -0.02em;
    font-size: clamp(1.35rem, 1.75vw, 2.25rem);
}

/* ── Botões ───────────────────────────────────────────────────────────────── */
.stButton > button, .stLinkButton > a, .stDownloadButton > button,
[data-testid="stFormSubmitButton"] > button {
    border-radius: 12px;
    font-weight: 600;
    border: 1px solid rgba(0,0,0,.09);
    box-shadow: 0 1px 2px rgba(0,0,0,.05);
    transition: transform .12s ease, box-shadow .12s ease;
}
.stButton > button:hover, .stLinkButton > a:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(0,0,0,.10);
}
.stButton > button[kind="primary"], [data-testid="stFormSubmitButton"] > button[kind="primary"] {
    background: #0071E3; border: none; color: #fff;
}
.stButton > button[kind="primary"]:hover { background: #0077ED; }

/* ── Abas em pílula ───────────────────────────────────────────────────────── */
/* Streamlit ≥1.59 trocou o baseweb por [role="tablist"] + [data-testid="stTab"];
   mantemos os seletores antigos junto por compatibilidade. */
.stTabs [data-baseweb="tab-list"], .stTabs [role="tablist"] {
    gap: 4px; background: #ECECEE; padding: 4px;
    border-radius: 12px; width: fit-content; border-bottom: none;
}
.stTabs [data-baseweb="tab"], .stTabs [data-testid="stTab"] {
    border-radius: 9px; padding: 6px 18px; font-weight: 600; color: #3A3A3C;
    border-bottom: none;
}
.stTabs [aria-selected="true"] {
    background: #FFFFFF !important; color: #1D1D1F !important;
    box-shadow: 0 1px 3px rgba(0,0,0,.10);
}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"],
.stTabs [data-testid="stTab"] > div:not([data-testid]) { display: none; }

/* ── Expanders, alertas, tabelas, formulários ─────────────────────────────── */
[data-testid="stExpander"] {
    background: #FFFFFF; border: 1px solid rgba(0,0,0,.06);
    border-radius: 14px; overflow: hidden; box-shadow: 0 1px 2px rgba(0,0,0,.03);
}
[data-testid="stExpander"] summary { font-weight: 600; }
[data-testid="stAlert"] { border-radius: 14px; border: none; }
[data-testid="stDataFrame"], [data-testid="stDataEditor"] {
    border: 1px solid rgba(0,0,0,.06); border-radius: 14px;
    overflow: hidden; background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,.03);
}
[data-testid="stForm"] { background:#fff; border:1px solid rgba(0,0,0,.06); border-radius:16px; }
[data-baseweb="input"], [data-baseweb="select"] > div, .stDateInput > div > div {
    border-radius: 10px !important;
}
[data-testid="stFileUploaderDropzone"] {
    border-radius: 14px; border: 1.5px dashed rgba(0,0,0,.15); background: #FFFFFF;
}

/* ── Barra lateral ────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background: #FFFFFF; border-right: 1px solid rgba(0,0,0,.06);
}
[data-testid="stSidebarNav"] a {
    border-radius: 10px; font-weight: 500; margin: 1px 8px; padding: 2px 6px;
}
[data-testid="stSidebarNav"] a:hover { background: #F2F2F4; }

/* ── Componentes próprios ─────────────────────────────────────────────────── */
.ui-hero { display: flex; align-items: center; gap: 18px; margin-bottom: .4rem; }
.ui-hero-icone {
    font-size: 2rem; line-height: 1; width: 64px; height: 64px; flex: 0 0 64px;
    display: flex; align-items: center; justify-content: center;
    background: linear-gradient(145deg, #FFFFFF, #EDEDEF);
    border: 1px solid rgba(0,0,0,.06); border-radius: 18px;
    box-shadow: 0 2px 6px rgba(0,0,0,.06);
}
.ui-hero h1 { font-size: 1.85rem; margin: 0; padding: 0; }
.ui-hero p  { margin: 2px 0 0; color: #6E6E73; font-size: .95rem; }

.ui-secao { display: flex; align-items: flex-start; gap: 14px; margin: .6rem 0 .9rem; }
.ui-passo {
    flex: 0 0 34px; width: 34px; height: 34px; margin-top: 2px;
    display: flex; align-items: center; justify-content: center;
    background: #0071E3; color: #fff; font-weight: 700; font-size: .95rem;
    border-radius: 50%; box-shadow: 0 2px 6px rgba(0,113,227,.35);
}
.ui-secao h2 { font-size: 1.3rem; margin: 0; padding: 0; }
.ui-secao p  { margin: 3px 0 0; color: #6E6E73; font-size: .92rem; }

.ui-card {
    background: #FFFFFF; border: 1px solid rgba(0,0,0,.06);
    border-radius: 16px; padding: 18px 20px; height: 100%;
    box-shadow: 0 1px 3px rgba(0,0,0,.04);
}
.ui-card h3 { font-size: 1.02rem; margin: 0 0 4px; }
.ui-card p  { margin: 0; color: #6E6E73; font-size: .88rem; line-height: 1.45; }
.ui-card .ui-badge { margin-top: 10px; }

.ui-badge {
    display: inline-block; padding: 3px 10px; border-radius: 999px;
    font-size: .74rem; font-weight: 600; letter-spacing: .01em;
}
.ui-badge-verde    { background: #E8F7EC; color: #1E7B34; }
.ui-badge-azul     { background: #E8F1FD; color: #0059B8; }
.ui-badge-laranja  { background: #FFF3E0; color: #B15C00; }
.ui-badge-cinza    { background: #F0F0F2; color: #55555A; }

/* ── Chat, status e progresso ─────────────────────────────────────────────── */
[data-testid="stChatMessage"] {
    background: #FFFFFF; border: 1px solid rgba(0,0,0,.06);
    border-radius: 16px; box-shadow: 0 1px 2px rgba(0,0,0,.03);
}
[data-testid="stChatInput"] {
    border-radius: 14px; border: 1px solid rgba(0,0,0,.09);
    background: #FFFFFF; box-shadow: 0 1px 3px rgba(0,0,0,.05);
}
[data-testid="stStatusWidget"] { border-radius: 12px; }
[data-testid="stStatus"] { border-radius: 14px; }
.stProgress > div > div > div > div { background: #0071E3; }
[data-testid="stPopover"] > div { border-radius: 12px; }

/* Nota didática clara (substitui os callouts escuros antigos) */
.ui-nota {
    padding: .85rem 1.1rem; margin: .4rem 0 1rem;
    background: #F0F6FF; border-left: 4px solid #0071E3; border-radius: 10px;
    color: #1D1D1F; font-size: .92rem; line-height: 1.5;
}
.ui-nota .ui-nota-titulo {
    display: block; font-size: .74rem; font-weight: 700; letter-spacing: .05em;
    text-transform: uppercase; color: #0059B8; margin-bottom: 2px;
}

/* page_link como cartão (home) */
[data-testid="stPageLink"] a {
    background: #FFFFFF; border: 1px solid rgba(0,0,0,.06);
    border-radius: 14px; padding: 12px 16px !important;
    box-shadow: 0 1px 2px rgba(0,0,0,.04);
    transition: transform .12s ease, box-shadow .12s ease;
}
[data-testid="stPageLink"] a:hover {
    transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,.10);
    text-decoration: none;
}
[data-testid="stPageLink"] a p { font-weight: 600; }
</style>
"""


def aplicar_estilo():
    """Injeta o design system. Chamar 1× por página, após o set_page_config."""
    st.markdown(_CSS, unsafe_allow_html=True)


def cabecalho(icone: str, titulo: str, subtitulo: str = ""):
    """Cabeçalho padrão da página: ícone em 'squircle' + título + frase-guia."""
    st.markdown(
        f"""<div class="ui-hero">
              <div class="ui-hero-icone">{icone}</div>
              <div><h1>{titulo}</h1><p>{subtitulo}</p></div>
            </div>""",
        unsafe_allow_html=True,
    )


def secao(numero, titulo: str, descricao: str = ""):
    """Título de seção com o passo numerado — guia o olho na ordem certa."""
    st.markdown(
        f"""<div class="ui-secao">
              <div class="ui-passo">{numero}</div>
              <div><h2>{titulo}</h2><p>{descricao}</p></div>
            </div>""",
        unsafe_allow_html=True,
    )


def badge(texto: str, cor: str = "cinza") -> str:
    """HTML de um selo (verde | azul | laranja | cinza) para usar em markdown."""
    return f'<span class="ui-badge ui-badge-{cor}">{texto}</span>'


def nota(texto: str, titulo: str = ""):
    """Callout claro e didático (borda azul à esquerda), no lugar de st.info."""
    rotulo = f'<span class="ui-nota-titulo">{titulo}</span>' if titulo else ""
    st.markdown(f'<div class="ui-nota">{rotulo}{texto}</div>', unsafe_allow_html=True)
