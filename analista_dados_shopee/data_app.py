import streamlit as st
import socket
import subprocess
import os
import sys
import time
from pathlib import Path

st.set_page_config(page_title="Estúdio Shopee DW", page_icon="📊", layout="wide")

# ================= 1. TRATAMENTO DE CAMINHOS =================
# Ajuste ROOT_DIR para apontar para a raiz ONDE ESTÁ O llm.py unificado!
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent # Assume que data_app.py está na subpasta "analista_dados_shopee" e llm.py está na raiz

def checar_porta(porta=8000):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', porta)) == 0

if 'motor_ia_pronto' not in st.session_state: 
    st.session_state.motor_ia_pronto = False

# ================= 2. AUTO-BOOT DO LITELLM =================
if not st.session_state.motor_ia_pronto:
    with st.status("🚀 Verificando Motor de IA Unificado (Porta 8000)...", expanded=True) as status:
        if not checar_porta(8000):
            st.write("Iniciando o Proxy LiteLLM em background...")
            llm_script_path = str(ROOT_DIR / "llm.py")
            log_path = str(ROOT_DIR / "llm_boot_dados.log") # Nome separado para não conflitar com as imagens
            
            # Limpa o log antigo
            if os.path.exists(log_path):
                try: os.remove(log_path)
                except: pass
            
            env_utf8 = os.environ.copy()
            env_utf8["PYTHONIOENCODING"] = "utf-8"
            comando_shell = f'"{sys.executable}" -u "{llm_script_path}" > "{log_path}" 2>&1'
            subprocess.Popen(comando_shell, shell=True, cwd=str(ROOT_DIR), env=env_utf8)
            
            console_preview = st.empty()
            conectado = False
            
            # Tenta conectar por 20 segundos
            for _ in range(40): 
                time.sleep(0.5)
                # Exibe o log do LiteLLM em tempo real na tela (Ótimo UX)
                try:
                    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                        logs_atuais = f.read()
                        if logs_atuais.strip():
                            console_preview.code(logs_atuais[-2000:], language="bash")
                except: pass
                
                if checar_porta(8000):
                    conectado = True
                    break
                    
            if conectado:
                status.update(label="Motor IA Online na Porta 8000!", state="complete", expanded=False)
                st.session_state.motor_ia_pronto = True
                time.sleep(1)
                st.rerun()
            else:
                status.update(label="Falha no Boot da IA (Timeout)", state="error", expanded=True)
                st.stop()
        else:
            status.update(label="Motor IA já estava Online (Porta 8000)!", state="complete", expanded=False)
            st.session_state.motor_ia_pronto = True
            time.sleep(0.5)
            st.rerun()

# ================= 3. INTERFACE PRINCIPAL =================
if st.session_state.motor_ia_pronto:
    st.title("📊 Data Warehouse - Estúdio Shopee")
    st.markdown("""
    Bem-vindo ao **Centro de Comando Empresarial** da sua fazenda de impressão 3D.
    
    **Navegue pelo menu lateral para operar a loja:**
    * **🏭 Engenharia de Fábrica:** Atualize os custos do seu filamento, energia e taxas de perda/refugo.
    * **🔄 Sincronização:** Extraia os dados cruciais da Shopee (Catálogo, Pedidos, Comportamento e Ads).
    * **🧠 Cérebro IA:** Acorde o Conselho de Administração (RunPod) para auditar a sua loja e disparar promoções autônomas.
    * **💬 Assistente de Dados:** Interrogue e converse livremente com os seus dados usando o modelo Groq de 70B.
    """)
    
    st.divider()
    st.success("✅ Conexão com o Motor Unificado de IA (LiteLLM) estabelecida com sucesso. O sistema está 100% pronto para operar.")