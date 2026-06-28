import streamlit as st
import psycopg2
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

# Configuração de caminhos e ambiente
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

# ATUALIZADO: Apontando para o ficheiro correto
load_dotenv(ROOT_DIR / "CHAVES_DADOS.env")

# ATUALIZADO: Importação direta a partir da raiz garantida pelo sys.path
from workers.sync_catalogo import sincronizar_catalogo
from workers.sync_pedidos import sincronizar_pedidos
from workers.sync_trafego_ads import sincronizar_trafego_ads

st.set_page_config(page_title="Sincronização", page_icon="🔄", layout="wide")

# ==============================================================================
# FUNÇÕES DE CONTROLE DE BANCO DE DADOS (Blindadas contra Timeout)
# ==============================================================================
def get_db_connection():
    try:
        return psycopg2.connect(
            host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"),
            database=os.getenv("POSTGRES_DB"), user=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD")
        )
    except Exception as e:
        st.error(f"🚨 Falha de conexão ao banco de dados: {e}")
        st.stop()

def obter_ultima_sincronizacao(modulo):
    """Lê a tabela de controle para saber de onde devemos começar a buscar."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT data_fim_coleta FROM sys_controle_sync 
                WHERE modulo = %s AND status = 'SUCESSO' 
                ORDER BY data_fim_coleta DESC LIMIT 1;
            """, (modulo,))
            resultado = cur.fetchone()
    return resultado[0] if resultado else None

def registrar_sincronizacao(modulo, data_inicio, data_fim, status, registros):
    """Grava no banco que o lote foi concluído com sucesso."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO sys_controle_sync (modulo, data_inicio_coleta, data_fim_coleta, status, registros_afetados)
                VALUES (%s, %s, %s, %s, %s);
            """, (modulo, data_inicio, data_fim, status, registros))
        conn.commit()

# ==============================================================================
# MOTOR DE FATIAMENTO DE TEMPO (Proteção contra a Shopee API)
# ==============================================================================
def fatiar_periodo(start_date, end_date, max_dias=14):
    """
    A Shopee só aceita 15 dias por chamada. 
    Esta função quebra 6 meses em vários blocos de 14 dias para evitar bloqueios.
    """
    blocos = []
    atual = start_date
    while atual < end_date:
        proximo = min(atual + timedelta(days=max_dias), end_date)
        blocos.append((atual, proximo))
        atual = proximo
    return blocos

# ==============================================================================
# INTERFACE E LÓGICA DO BOTÃO
# ==============================================================================
st.title("🔄 Sincronização On-Demand")
st.markdown("Busque as atualizações da Shopee manualmente. O sistema calcula o *Delta* automaticamente e atualiza as métricas da IA (Estrelas, Likes, Ads).")

# Exibe o status atual na tela
st.subheader("Status do Data Warehouse")
col1, col2 = st.columns(2)
ultima_sync_pedidos = obter_ultima_sincronizacao('PEDIDOS')
ultima_sync_trafego = obter_ultima_sincronizacao('TRAFEGO_ADS')

with col1:
    st.info(f"📦 Última extração de Pedidos: **{ultima_sync_pedidos.strftime('%d/%m/%Y %H:%M') if ultima_sync_pedidos else 'Nunca'}**")
with col2:
    st.info(f"📈 Última extração de Tráfego/Ads: **{ultima_sync_trafego.strftime('%d/%m/%Y') if ultima_sync_trafego else 'Nunca'}**")

st.divider()

if st.button("🚀 INICIAR SINCRONIZAÇÃO COMPLETA", type="primary", use_container_width=True):
    
    agora = datetime.now()
    
    # ---------------------------------------------------------
    # 1. ATUALIZA O CATÁLOGO (Rápido, apenas os ativos)
    # ---------------------------------------------------------
    with st.status("1. Sincronizando Catálogo de Produtos e Reputação...", expanded=True) as status:
        st.write("Buscando anúncios, estoque, likes e estrelas...")
        resultado_cat = sincronizar_catalogo()
        if resultado_cat["status"] == "sucesso":
            status.update(label=f"Catálogo atualizado! ({resultado_cat['produtos']} produtos e variações mapeadas)", state="complete")
        else:
            status.update(label="Falha ao atualizar catálogo.", state="error")
            st.stop()

    # ---------------------------------------------------------
    # 2. CARGA DE PEDIDOS E FINANCEIRO (Fatiada)
    # ---------------------------------------------------------
    with st.status("2. Sincronizando Motor Financeiro e Pedidos...", expanded=True) as status:
        data_inicio = ultima_sync_pedidos or datetime(2026, 1, 26)
        
        if data_inicio >= agora - timedelta(minutes=10):
            st.write("✅ Pedidos já estão atualizados.")
            status.update(label="Pedidos atualizados.", state="complete")
        else:
            blocos_tempo = fatiar_periodo(data_inicio, agora, max_dias=14)
            barra_progresso = st.progress(0)
            
            total_pedidos = 0
            for i, (inicio_bloco, fim_bloco) in enumerate(blocos_tempo):
                st.write(f"Extraindo período: {inicio_bloco.strftime('%d/%m/%Y')} a {fim_bloco.strftime('%d/%m/%Y')}")
                
                res = sincronizar_pedidos(inicio_bloco, fim_bloco)
                
                if res["status"] == "sucesso":
                    total_pedidos += res["registros"]
                    registrar_sincronizacao('PEDIDOS', inicio_bloco, fim_bloco, 'SUCESSO', res["registros"])
                else:
                    st.error(f"Erro na extração do bloco {inicio_bloco.date()}")
                    break
                    
                barra_progresso.progress((i + 1) / len(blocos_tempo))
                
            status.update(label=f"Motor Financeiro atualizado! ({total_pedidos} registros processados)", state="complete")

    # ---------------------------------------------------------
    # 3. CARGA DE TRÁFEGO E ADS
    # ---------------------------------------------------------
    with st.status("3. Sincronizando Tráfego, Ads e Comportamento...", expanded=True) as status:
        data_inicio_trafego = ultima_sync_trafego or datetime(2026, 1, 26)
        
        # O tráfego consolida o D-1, então vamos até "ontem"
        ontem = datetime.now() - timedelta(days=1)
        
        if data_inicio_trafego.date() >= ontem.date():
            st.write("✅ Tráfego já está atualizado até o fechamento de ontem.")
            status.update(label="Tráfego atualizado.", state="complete")
        else:
            st.write(f"Iniciando busca diária desde {data_inicio_trafego.strftime('%d/%m/%Y')}...")
            res_trafego = sincronizar_trafego_ads(data_inicio_trafego, ontem)
            
            if res_trafego["status"] == "sucesso":
                registrar_sincronizacao('TRAFEGO_ADS', data_inicio_trafego, ontem, 'SUCESSO', res_trafego["registros"])
                status.update(label=f"Tráfego atualizado! ({res_trafego['registros']} interações processadas)", state="complete")
            else:
                status.update(label="Falha ao extrair métricas de Ads.", state="error")
                
    st.balloons()
    st.success("🎉 Data Warehouse 100% Sincronizado! A IA já tem todos os dados necessários.")