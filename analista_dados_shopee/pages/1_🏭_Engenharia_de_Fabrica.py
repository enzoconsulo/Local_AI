import streamlit as st
import psycopg2
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

# Função para rodar queries que retornam tabelas
def run_query(query, params=None):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            if cur.description:
                col_names = [desc[0] for desc in cur.description]
                return pd.DataFrame(cur.fetchall(), columns=col_names)
            return pd.DataFrame()

# Função para executar inserções
def run_insert(query, params):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
            conn.commit()
        return True
    except Exception as e:
        st.error(f"Erro de Banco de Dados: {e}")
        return False

# ==============================================================================
# INTERFACE DO USUÁRIO
# ==============================================================================
st.title("⚙️ Engenharia de Fábrica e Insumos")
st.markdown("Alimente os custos de materiais, energia e perdas (refugo). A IA usará isso para auditar a sua operação de forma cirúrgica.")

tab_materiais, tab_maquinas, tab_mapeamento = st.tabs(["🛒 Filamentos & Embalagens", "🖨️ Máquinas 3D", "🔗 Mapeamento de Peças"])

# ----------------- ABA 1: MATERIAIS -----------------
with tab_materiais:
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("Cadastrar Novo Insumo")
        with st.form("form_material", clear_on_submit=True):
            nome = st.text_input("Nome (Ex: PETG Preto Fosco)")
            tipo = st.selectbox("Tipo de Insumo", ["Filamento", "Resina", "Embalagem", "Outro"])
            custo = st.number_input("Custo do Lote Fechado (Ex: Preço de 1KG) - R$", min_value=0.0, format="%.2f")
            unidade = st.selectbox("Unidade Base", ["kg", "unidade", "litro"])
            # NOVO: Controle de Estoque
            estoque = st.number_input("Estoque Físico Atual (na medida escolhida)", min_value=0.0, format="%.2f", help="A IA usará isso para prever rupturas logísticas.")
            
            if st.form_submit_button("💾 Salvar Material"):
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
        # ATUALIZADO: Mostrando o estoque
        df_mat = run_query("SELECT id_material as ID, nome as Nome, tipo as Categoria, custo_por_unidade as Custo, estoque_atual as Estoque, unidade_medida as Unidade FROM dim_materiais ORDER BY id_material DESC")
        st.dataframe(df_mat, use_container_width=True, hide_index=True)

# ----------------- ABA 2: MÁQUINAS -----------------
with tab_maquinas:
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("Cadastrar Impressora")
        with st.form("form_maquina", clear_on_submit=True):
            nome_maq = st.text_input("Modelo da Máquina (Ex: Bambu Lab P1P)")
            custo_kwh = st.number_input("Custo de Energia por Hora (R$/h)", min_value=0.0, format="%.4f", help="Calcule o consumo (kW) * Tarifa da concessionária (R$/kWh)")
            
            if st.form_submit_button("💾 Salvar Impressora"):
                if nome_maq:
                    if run_insert("INSERT INTO dim_maquinas (nome_modelo, custo_energia_hora) VALUES (%s, %s)", (nome_maq, custo_kwh)):
                        st.success(f"Máquina '{nome_maq}' salva!")
                        st.rerun()
                else:
                    st.warning("O nome não pode estar vazio.")

    with col2:
        st.subheader("Frota Ativa")
        df_maq = run_query("SELECT id_maquina as ID, nome_modelo as Máquina, custo_energia_hora as Custo_Hora, status as Status FROM dim_maquinas ORDER BY id_maquina DESC")
        st.dataframe(df_maq, use_container_width=True, hide_index=True)

# ----------------- ABA 3: MAPEAMENTO -----------------
with tab_mapeamento:
    st.subheader("🔗 Vínculo Produtivo: Shopee ↔ Fábrica")
    
    try:
        df_var = run_query("""
            SELECT v.model_id, p.nome_atual || ' (' || v.nome_variacao || ')' as produto_nome
            FROM dim_variacoes v
            JOIN dim_produtos p ON v.item_id = p.item_id
            WHERE p.status_shopee = 'NORMAL'
            ORDER BY p.nome_atual;
        """)
        df_mat = run_query("SELECT id_material, nome, unidade_medida FROM dim_materiais")
        df_maq = run_query("SELECT id_maquina, nome_modelo FROM dim_maquinas")
        
        if df_var.empty or df_mat.empty or df_maq.empty:
            st.warning("⚠️ Você precisa de cadastrar pelo menos 1 Material, 1 Máquina e Sincronizar o Catálogo da Shopee antes de fazer o mapeamento.")
        else:
            col1, col2 = st.columns([1, 2])
            
            with col1:
                with st.form("form_map", clear_on_submit=False):
                    var_dict = dict(zip(df_var['produto_nome'], df_var['model_id']))
                    mat_dict = dict(zip(df_mat['nome'] + " [" + df_mat['unidade_medida'] + "]", df_mat['id_material']))
                    maq_dict = dict(zip(df_maq['nome_modelo'], df_maq['id_maquina']))

                    sel_var = st.selectbox("Selecione o Anúncio/Variação da Shopee", var_dict.keys())
                    sel_mat = st.selectbox("Qual material é usado?", mat_dict.keys())
                    sel_maq = st.selectbox("Qual máquina imprime?", maq_dict.keys())
                    
                    peso = st.number_input("Peso Líquido da Peça (em Gramas)", min_value=0.0, value=50.0, format="%.1f")
                    tempo = st.number_input("Tempo Médio de Impressão (Minutos)", min_value=0, value=60)
                    custo_emb = st.number_input("Custo Fixo Embalagem (Caixa+Plástico Bolha) - R$", min_value=0.0, value=1.50, format="%.2f")
                    
                    # NOVO: Controle de Refugo
                    perda = st.number_input("Taxa de Perda / Refugo Esperado (%)", min_value=0.0, max_value=100.0, value=5.0, format="%.1f", help="Quantas impressões falham em média? A IA ajustará o seu custo final absorvendo este prejuízo.")

                    if st.form_submit_button("🔗 Salvar Mapeamento de Custos"):
                        query = """
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
                        if run_insert(query, (var_dict[sel_var], mat_dict[sel_mat], maq_dict[sel_maq], peso, tempo, custo_emb, perda)):
                            st.success("Custo mapeado! A IA já sabe calcular o lucro real desta peça.")
            
            with col2:
                # ATUALIZADO: Mostrando a taxa de perda
                df_mapeados = run_query("""
                    SELECT p.nome_atual as "Produto", v.nome_variacao as "Variação",
                           m.peso_gramas as "Gramas", m.taxa_perda_percentual as "Refugo (%)", 
                           m.tempo_impressao_minutos as "Minutos"
                    FROM map_engenharia_produto m
                    JOIN dim_variacoes v ON m.model_id = v.model_id
                    JOIN dim_produtos p ON v.item_id = p.item_id
                """)
                st.dataframe(df_mapeados, use_container_width=True, hide_index=True)
                
    except Exception as e:
        st.info("Execute a Sincronização do Catálogo na aba ao lado para carregar os produtos da Shopee aqui.")