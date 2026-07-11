import streamlit as st

st.set_page_config(page_title="Estúdio Shopee DW", page_icon="📊", layout="wide")

# ================= 1. INFERÊNCIA DIRETA POR API =================
# O Cérebro usa a OpenAI diretamente; não existe proxy local, porta 8000 ou GPU a iniciar.
st.session_state.motor_ia_pronto = True

# ================= 2. INTERFACE PRINCIPAL =================
if st.session_state.motor_ia_pronto:
    st.title("📊 Data Warehouse - Estúdio Shopee")
    st.markdown("""
    Bem-vindo ao **Centro de Comando Empresarial** da sua fazenda de impressão 3D.
    
    **Navegue pelo menu lateral para operar a loja:**
    * **🏭 Engenharia de Fábrica:** Atualize os custos do seu filamento, energia e taxas de perda/refugo.
    * **🔄 Sincronização:** Extraia os dados cruciais da Shopee (Catálogo, Pedidos, Comportamento e Ads).
    * **🧠 Cérebro IA:** Analise a loja via OpenAI, com previsões determinísticas, cache e checkpoint local.
    * **💬 Assistente de Dados:** Interrogue e converse livremente com os seus dados usando o modelo Groq de 70B.
    """)
    
    st.divider()
    st.success("✅ Aplicação pronta. A OpenAI será chamada apenas quando a análise exigir novos dados.")
