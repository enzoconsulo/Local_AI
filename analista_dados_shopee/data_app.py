import streamlit as st

from utils.ui import aplicar_estilo, cabecalho, badge

st.set_page_config(page_title="Estúdio Shopee DW", page_icon="📊", layout="wide")
aplicar_estilo()

# O Cérebro usa a OpenAI diretamente; não existe proxy local, porta 8000 ou GPU a iniciar.
st.session_state.motor_ia_pronto = True

cabecalho("📊", "Estúdio Shopee DW", "O centro de comando da sua fazenda de impressão 3D.")

# ── Status rápido do ambiente ─────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def _status_banco():
    try:
        from utils.db_pool import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM dim_produtos WHERE item_id > 0")
                produtos = cur.fetchone()[0]
                cur.execute("SELECT MAX(data_execucao) FROM sys_controle_sync WHERE status='SUCESSO'")
                ultima = cur.fetchone()[0]
        return True, produtos, ultima
    except Exception:
        return False, 0, None

banco_ok, qtd_produtos, ultima_sync = _status_banco()
if banco_ok:
    ultima_txt = ultima_sync.strftime("%d/%m %H:%M") if ultima_sync else "nunca"
    st.markdown(
        badge("● Banco conectado", "verde") + "&nbsp;&nbsp;"
        + badge(f"{qtd_produtos} produtos no DW", "azul") + "&nbsp;&nbsp;"
        + badge(f"Última sincronização: {ultima_txt}", "cinza"),
        unsafe_allow_html=True,
    )
else:
    st.error("🔌 Banco de dados fora do ar — rode `run_local.ps1` (ele sobe o Docker e valida tudo).")

st.markdown("")

# ── Navegação em cartões ──────────────────────────────────────────────────────
PAGINAS = [
    ("pages/0_📊_Visao_Central.py", "📊 Visão Central",
     "Comece por aqui: KPIs, funil, saúde da conta, boost grátis, voucher e o plano de ação.", "análise grátis", "verde"),
    ("pages/2_🔄_Sincronizacao.py", "🔄 Sincronização",
     "API (catálogo, pedidos, lucro) e upload das planilhas do Seller Center.", "dados", "azul"),
    ("pages/6_💰_Lucro_Real.py", "💰 Lucro Real",
     "Mapeie filamento + peso em 2 passos e veja o lucro líquido de cada produto.", "análise grátis", "verde"),
    ("pages/3_🧠_Cerebro_IA.py", "🧠 Cérebro IA",
     "Auditoria estratégica via OpenAI com cache — paga só pelo produto que mudou.", "IA paga", "laranja"),
    ("pages/4_💬_Chat_Assistente.py", "💬 Chat Assistente",
     "Pergunte qualquer coisa sobre seus dados em linguagem natural.", "IA paga", "laranja"),
    ("pages/1_🏭_Engenharia_de_Fabrica.py", "🏭 Engenharia de Fábrica",
     "Cadastro fino de máquinas, energia, refugo e custos por variação.", "opcional", "cinza"),
    ("pages/5_🧵_Mapeamento_Insumos.py", "🧵 Mapeamento de Insumos",
     "Vínculo detalhado insumo ↔ produto para quem quer precisão máxima.", "opcional", "cinza"),
]

for linha in range(0, len(PAGINAS), 3):
    cols = st.columns(3)
    for col, (arquivo, titulo, descricao, selo, cor) in zip(cols, PAGINAS[linha:linha + 3]):
        with col:
            st.markdown(
                f"""<div class="ui-card">
                      <h3>{titulo}</h3>
                      <p>{descricao}</p>
                      <div class="ui-badge ui-badge-{cor}">{selo}</div>
                    </div>""",
                unsafe_allow_html=True,
            )
            st.page_link(arquivo, label="Abrir", icon="→")
    st.markdown("")

st.divider()
st.markdown(
    """**Primeira vez por aqui?** O caminho feliz é: **🔄 Sincronização** (puxa a loja inteira)
→ **💰 Lucro Real** (2 minutos mapeando custos) → **📊 Visão Central** (decisões prontas, sem gastar IA)."""
)
