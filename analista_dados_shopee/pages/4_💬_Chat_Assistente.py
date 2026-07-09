import streamlit as st
import psycopg2
import pandas as pd
import requests
import json
import re
import os
import sys
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Configuração de Ambiente
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))
load_dotenv(ROOT_DIR / "CHAVES_DADOS.env")

st.set_page_config(page_title="Assistente IA", page_icon="💬", layout="wide")

# ==============================================================================
# FUNÇÕES DE BANCO DE DADOS BLINDADAS
# ==============================================================================
def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"),
        database=os.getenv("POSTGRES_DB"), user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD")
    )

def run_query(query):
    """Executa consultas de leitura no banco de dados e retorna um DataFrame Pandas"""
    query_normalizada = query.strip().lstrip("(").strip().upper()
    if not query_normalizada.startswith("SELECT") and not query_normalizada.startswith("WITH"):
        raise ValueError("Por segurança, apenas comandos SELECT são permitidos neste chat.")
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                if cur.description:
                    col_names = [desc[0] for desc in cur.description]
                    df = pd.DataFrame(cur.fetchall(), columns=col_names)
                    return df.head(50)
                else:
                    return pd.DataFrame()
    except Exception as e:
        raise e

def obter_contexto_estrategico_atual():
    """Lê o Diário de Bordo (log_acoes) para o Groq saber as últimas decisões tomadas."""
    try:
        # Puxamos as últimas 10 ações tomadas na loja para dar contexto à IA
        df = run_query("""
            SELECT p.nome_atual as produto, l.tipo_acao, l.detalhe_acao, l.impacto_projetado as projecao_ia, l.data_aplicacao
            FROM log_acoes_shopee l
            JOIN dim_produtos p ON l.item_id = p.item_id
            WHERE l.status_api = 'SUCESSO'
            ORDER BY l.data_aplicacao DESC
            LIMIT 10
        """)
        if df.empty:
            return "Nenhuma ação foi aprovada e executada na loja recentemente."
        # Converte as datas para string para serialização JSON
        df['data_aplicacao'] = df['data_aplicacao'].astype(str)
        return df.to_json(orient="records", force_ascii=False)
    except Exception:
        return "Erro ao carregar contexto estratégico do Diário de Bordo."

# ==============================================================================
# MOTOR DO AGENTE IA (Groq Text-to-SQL via LiteLLM)
# ==============================================================================
LITELLM_URL = "http://localhost:8000/v1/chat/completions" # Porta 8000 conforme definimos no boot

# SCHEMA ATUALIZADO (Com todas as colunas da Migration 02)
SCHEMA_DO_BANCO = """
O banco de dados PostgreSQL contém as seguintes tabelas relacionais da loja Shopee:
1. dim_produtos (item_id BIGINT, nome_atual VARCHAR, category_id BIGINT, status_shopee VARCHAR, data_criacao TIMESTAMP, nota_media_estrelas DECIMAL, likes_count INTEGER, dias_pre_encomenda INTEGER)
2. dim_variacoes (model_id BIGINT, item_id BIGINT, nome_variacao VARCHAR, sku_variacao VARCHAR, preco_venda_atual DECIMAL, estoque_shopee INTEGER)
3. map_engenharia_produto (model_id BIGINT, id_material INTEGER, id_maquina INTEGER, peso_gramas DECIMAL, tempo_impressao_minutos INTEGER, custo_embalagem DECIMAL, taxa_perda_percentual DECIMAL)
4. fato_pedidos_venda (order_sn VARCHAR, data_hora_criacao TIMESTAMP, uf_destino CHAR, status_pedido VARCHAR, motivo_cancelamento_devolucao VARCHAR)
5. fato_itens_pedido (order_sn VARCHAR, model_id BIGINT, quantidade INTEGER, preco_praticado DECIMAL)
6. fato_repasse_escrow (order_sn VARCHAR, comissao_shopee DECIMAL, taxa_servico DECIMAL, taxa_transacao DECIMAL, custo_frete_reverso DECIMAL, lucro_liquido_absoluto DECIMAL)
7. fato_trafego_diario (item_id BIGINT, data DATE, visitantes_unicos INTEGER, taxa_rejeicao DECIMAL, adicoes_carrinho INTEGER)
8. fato_ads_palavras_chave (item_id BIGINT, keyword VARCHAR, data DATE, impressoes INTEGER, cliques INTEGER, custo_total DECIMAL, gmv_gerado DECIMAL)
9. log_acoes_shopee (id_log SERIAL, item_id BIGINT, tipo_acao VARCHAR, detalhe_acao TEXT, impacto_projetado JSONB, data_aplicacao TIMESTAMP, status_api VARCHAR)

CHAVES ESTRANGEIRAS CRUCIAIS:
- fato_itens_pedido.order_sn -> fato_pedidos_venda.order_sn
- fato_repasse_escrow.order_sn -> fato_pedidos_venda.order_sn
- fato_itens_pedido.model_id -> dim_variacoes.model_id
- dim_variacoes.item_id -> dim_produtos.item_id
"""

def criar_prompt_sistema():
    estrategias_atuais = obter_contexto_estrategico_atual()
    data_hoje = datetime.now().strftime("%Y-%m-%d")
    
    return f"""Você é o Consultor Analítico de E-commerce Sênior da Fazenda de Impressão 3D.
Sua função é conversar com o dono da loja de forma direta, clara e orientada a lucro.

INFORMAÇÃO TEMPORAL: A data de hoje é {data_hoje}. Use isto como referência para consultas como 'neste mês' ou 'últimos 7 dias' (CURRENT_DATE - INTERVAL '7 days').

AÇÕES EXECUTADAS RECENTEMENTE NA LOJA (Para o seu contexto):
{estrategias_atuais}

REGRAS DE FUNCIONAMENTO (Padrão ReAct):
1. Se a resposta puder ser dada baseada nas AÇÕES EXECUTADAS acima ou conhecimento geral, apenas responda com texto analítico.
2. Se o usuário pedir cálculos de lucro, cruzamentos, métricas de tráfego, estrelas ou dados históricos, você DEVE escrever uma query SQL para extrair o dado do PostgreSQL.
3. Se você decidir gerar um SQL, ENVOLVA O COMANDO ESTANQUE ENTRE AS TAGS ```sql e ```. 
4. O sistema irá executar o SQL e devolver-lhe os números (em formato de tabela) para você formular a resposta final.
5. Em SQLs, limite SEMPRE a resposta a um máximo de 50 linhas (LIMIT 50). Use aliases amigáveis para as colunas.
6. ATENÇÃO FINANCEIRA: O Lucro Líquido Real de uma venda é calculado subtraindo o custo de fabricação (em map_engenharia_produto) e as taxas (fato_repasse_escrow) do preco_praticado (fato_itens_pedido).

SCHEMA DO BANCO DE DADOS:
{SCHEMA_DO_BANCO}
"""

def enviar_para_llm(mensagens):
    """Envia o histórico para o Groq via Proxy LiteLLM."""
    payload = {
        "model": "chat-rapido", # O modelo Groq (Llama 3.3) configurado no boot_ia
        "messages": mensagens[-10:], # Envia apenas as últimas 10 mensagens para não estourar o limite de tokens do LLM
        "temperature": 0.1
    }
    try:
        res = requests.post(LITELLM_URL, json=payload, timeout=60)
        res.raise_for_status()
        return res.json()['choices'][0]['message']['content']
    except requests.exceptions.ConnectionError:
        return "❌ Erro: Não foi possível conectar ao LiteLLM na porta 8000. Verifique se o Motor Híbrido está rodando."
    except Exception as e:
        return f"❌ Erro de processamento na IA: {str(e)}"

def extrair_sql(texto):
    """Procura por código SQL embutido na resposta, com limpeza robusta."""
    match = re.search(r'```sql\s*(.*?)\s*```', texto, re.IGNORECASE | re.DOTALL)
    if match: 
        return match.group(1).strip()
    return None

# ==============================================================================
# INTERFACE DO CHAT E BOTÕES RÁPIDOS
# ==============================================================================
st.title("💬 Assistente de Dados (Groq Text-to-SQL)")
st.markdown("Interrogue o seu Data Warehouse. O LLM traduz as suas perguntas para consultas avançadas em milissegundos.")

# --- SEÇÃO DE ANÁLISES RÁPIDAS (QUICK ACTIONS) ---
st.write("⚡ **Análises Prontas (Clique para interrogar a IA):**")
col1, col2, col3, col4 = st.columns(4)

prompt_acionado = None

if col1.button("💸 Resumo de Lucratividade", use_container_width=True):
    prompt_acionado = "Qual foi o meu faturamento bruto e o lucro líquido absoluto nos últimos 7 dias?"
if col2.button("🩸 Sangramento de Ads", use_container_width=True):
    prompt_acionado = "Quais são as 5 palavras-chave de Ads que mais consumiram orçamento nos últimos 7 dias, e qual foi o GMV gerado por elas?"
if col3.button("⭐ Vitrine e Reputação", use_container_width=True):
    prompt_acionado = "Faça um ranking dos 5 produtos com mais likes (favoritos), mostrando também a nota média de estrelas de cada um."
if col4.button("🧠 Últimas Ações da IA", use_container_width=True):
    prompt_acionado = "Resuma rapidamente as últimas ações e alterações de preço que nós aprovamos na loja recentemente, e quais foram as projeções de impacto."

st.divider()

# --- MOTOR DE ESTADO DO CHAT ---
if "chat_history" not in st.session_state:
    st.session_state.chat_history = [{"role": "system", "content": criar_prompt_sistema()}]
    st.session_state.chat_history.append({
        "role": "assistant", 
        "content": "Olá, Mestre! Já carreguei as nossas últimas decisões e a estrutura do banco. O que deseja analisar hoje?"
    })

# Renderiza o chat
for msg in st.session_state.chat_history:
    if msg["role"] not in ["system", "tool_result"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

# --- CAPTURA DE INPUT (Botão ou Digitação) ---
user_input = st.chat_input("Ex: Qual variação de cor vendeu mais no mês passado?")

# Resolve qual prompt usar
input_final = prompt_acionado if prompt_acionado else user_input

if input_final:
    st.session_state.chat_history.append({"role": "user", "content": input_final})
    with st.chat_message("user"):
        st.markdown(input_final)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        
        with st.spinner("🧠 Consultor IA Analisando Dados..."):
            resposta_ia = enviar_para_llm(st.session_state.chat_history)
            
            codigo_sql = extrair_sql(resposta_ia)
            
            if codigo_sql:
                with st.status("⚙️ Executando Consulta Automática no PostgreSQL...", expanded=False):
                    st.code(codigo_sql, language="sql")
                    try:
                        df_resultado = run_query(codigo_sql)
                        if df_resultado.empty:
                            resultado_tabela = "A consulta retornou zero linhas. Não há dados para esse filtro."
                        else:
                            resultado_tabela = df_resultado.to_markdown(index=False)
                    except Exception as erro_bd:
                        resultado_tabela = f"Erro na execução do SQL: {str(erro_bd)}"
                        st.error(resultado_tabela)
                        
                    st.write("Dados recuperados da memória da loja!")

                # Injeta a resposta do SQL no histórico "por baixo dos panos"
                st.session_state.chat_history.append({"role": "assistant", "content": resposta_ia})
                
                instrucao_sistema = f"Resultado do PostgreSQL:\n{resultado_tabela}\nFormule a resposta final ao usuário de forma clara e executiva, omitindo que você usou SQL."
                st.session_state.chat_history.append({"role": "user", "content": instrucao_sistema}) 
                
                with st.spinner("✍️ Formulando Resposta Executiva..."):
                    resposta_final = enviar_para_llm(st.session_state.chat_history)
                    placeholder.markdown(resposta_final)
                    st.session_state.chat_history.append({"role": "assistant", "content": resposta_final})
            
            else:
                placeholder.markdown(resposta_ia)
                st.session_state.chat_history.append({"role": "assistant", "content": resposta_ia})