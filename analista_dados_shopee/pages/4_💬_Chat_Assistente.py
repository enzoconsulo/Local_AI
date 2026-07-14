"""
pages/4_💬_Chat_Assistente.py
=============================
UI do Assistente de Dados: chat text-to-SQL sobre o Data Warehouse.

Toda a inteligência mora em cerebro/consultor.py (núcleo sem Streamlit):
esta página só captura o input, injeta os callbacks visuais e renderiza.
Migrado do stack Groq/LiteLLM local para a API OpenAI direta, com o schema
atualizado até a migração 14 (views, materiais/máquinas, semântica de NULL).
"""

import sys
from pathlib import Path

import streamlit as st

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from cerebro import consultor
from cerebro.config import OPENAI_MODEL_CHAT

st.set_page_config(page_title="Assistente IA", page_icon="💬", layout="wide")

st.title("💬 Assistente de Dados (Text-to-SQL)")
st.markdown(
    "Interrogue o seu Data Warehouse em português. O consultor traduz a pergunta em SQL de leitura, "
    "executa com segurança e devolve a resposta executiva."
)

# ─── Análises rápidas ─────────────────────────────────────────────────────────
st.write("⚡ **Análises Prontas (clique para interrogar a IA):**")
col1, col2, col3, col4 = st.columns(4)

prompt_acionado = None
if col1.button("💸 Resumo de Lucratividade", use_container_width=True):
    prompt_acionado = "Qual foi o meu faturamento bruto e o lucro líquido absoluto (escrow) nos últimos 7 dias?"
if col2.button("🩸 Sangramento de Ads", use_container_width=True):
    prompt_acionado = (
        "Quais são os 5 produtos que mais consumiram investimento em Ads nos últimos 7 dias, "
        "e qual foi o GMV e o ROAS de cada um? Considere item_id 0 como a campanha global da loja."
    )
if col3.button("⭐ Vitrine e Reputação", use_container_width=True):
    prompt_acionado = "Faça um ranking dos 5 produtos com mais likes (favoritos), mostrando também a nota média de estrelas."
if col4.button("🧠 Últimas Ações da IA", use_container_width=True):
    prompt_acionado = "Resuma as últimas ações que aprovamos na loja e as projeções de impacto de cada uma."

st.divider()

# ─── Estado do chat ───────────────────────────────────────────────────────────
if "chat_history" not in st.session_state:
    st.session_state.chat_history = [
        {"role": "system", "content": consultor.construir_prompt_sistema()},
        {
            "role": "assistant",
            "content": "Olá! Já carreguei o schema do Data Warehouse e as últimas decisões da loja. O que deseja analisar?",
        },
    ]
if "telemetria_chat" not in st.session_state:
    st.session_state.telemetria_chat = {"chamadas": 0, "prompt_tokens": 0, "completion_tokens": 0}

# Renderiza o histórico visível (sistema e mensagens internas ficam ocultos)
for msg in st.session_state.chat_history:
    if msg["role"] == "system" or msg.get("oculta"):
        continue
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ─── Captura de input (botão ou digitação) ────────────────────────────────────
user_input = st.chat_input("Ex: Qual variação vendeu mais nos últimos 30 dias?")
input_final = prompt_acionado or user_input

if input_final:
    st.session_state.chat_history.append({"role": "user", "content": input_final})
    with st.chat_message("user"):
        st.markdown(input_final)

    with st.chat_message("assistant"):
        def ao_evento(tipo, dado):
            if tipo == "sql":
                with st.expander("⚙️ Consulta executada no PostgreSQL", expanded=False):
                    st.code(dado, language="sql")
            elif tipo == "tabela":
                if hasattr(dado, "empty") and not dado.empty:
                    with st.expander("📊 Dados recuperados", expanded=False):
                        st.dataframe(dado, use_container_width=True)
            elif tipo == "erro_sql":
                st.warning(f"A consulta foi rejeitada e será corrigida automaticamente: {dado}")

        with st.spinner("🧠 Consultor IA analisando os dados..."):
            novas_mensagens = consultor.executar_turno(
                st.session_state.chat_history,
                ao_evento=ao_evento,
                telemetria=st.session_state.telemetria_chat,
            )

        st.session_state.chat_history.extend(novas_mensagens)
        visiveis = [m for m in novas_mensagens if not m.get("oculta")]
        if visiveis:
            st.markdown(visiveis[-1]["content"])

# ─── Rodapé de transparência de custo ─────────────────────────────────────────
telemetria = st.session_state.telemetria_chat
if telemetria["chamadas"]:
    st.caption(
        f"💰 Sessão: {telemetria['chamadas']} chamada(s) ao modelo {OPENAI_MODEL_CHAT} · "
        f"{telemetria['prompt_tokens']:,} tokens de entrada · {telemetria['completion_tokens']:,} de saída."
    )
