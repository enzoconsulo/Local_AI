"""
utils/painel_ia.py
==================
Painel "⚙️ Motor de IA" (páginas 🧠 Cérebro e 💬 Chat): escolhe quem faz as
análises — o seu plano Claude pelo Claude Code, ou a API paga da OpenAI —,
com modelo e raciocínio por uso, e grava a escolha no CHAVES_DADOS.env.

A lógica mora em cerebro/provedor_ia.py; aqui é só interface.
"""

import streamlit as st

from cerebro import config, provedor_ia


def _indice(opcoes: list[str], valor: str) -> int:
    return opcoes.index(valor) if valor in opcoes else 0


def painel_motor_ia(chave: str) -> None:
    """Renderiza o painel. `chave` separa os widgets de cada página."""
    if st.session_state.pop(f"{chave}_salvo", False):
        st.toast("Motor de IA salvo no CHAVES_DADOS.env — vale a partir da próxima análise.", icon="✅")

    atual = provedor_ia.provedor()
    with st.expander(f"⚙️ Motor de IA — {provedor_ia.PROVEDORES[atual]}", expanded=False):
        opcoes_provedor = list(provedor_ia.PROVEDORES)
        escolha = st.radio(
            "Quem faz as análises", opcoes_provedor, index=_indice(opcoes_provedor, atual),
            format_func=provedor_ia.PROVEDORES.get, horizontal=True, key=f"{chave}_provedor",
        )
        valores = {"IA_PROVEDOR": escolha}

        if escolha == "claude_code":
            status = provedor_ia.status_claude_code()
            (st.success if status["ok"] else st.error)(status["mensagem"])
            st.caption(
                "Usa o limite do seu plano (janela de 5 horas e semanal), o mesmo do Claude Code no terminal. "
                "Nenhuma chave de API é usada e nada é cobrado por uso."
            )
            modelos = list(provedor_ia.MODELOS_CLAUDE)
            esforcos = list(provedor_ia.ESFORCOS)
            for coluna, (uso, rotulo) in zip(st.columns(3), provedor_ia.USOS.items()):
                with coluna:
                    st.markdown(f"**{rotulo}**")
                    modelo_atual = provedor_ia.modelo_claude(uso)
                    opcoes_modelo = modelos if modelo_atual in modelos else modelos + [modelo_atual]
                    valores[f"CLAUDE_MODEL_{uso.upper()}"] = st.selectbox(
                        "Modelo", opcoes_modelo, index=_indice(opcoes_modelo, modelo_atual),
                        format_func=lambda m: provedor_ia.MODELOS_CLAUDE.get(m, m).split(" — ")[0],
                        key=f"{chave}_modelo_{uso}",
                    )
                    valores[f"CLAUDE_EFFORT_{uso.upper()}"] = st.selectbox(
                        "Raciocínio", esforcos, index=_indice(esforcos, provedor_ia.esforco_claude(uso)),
                        format_func=provedor_ia.ESFORCOS.get, key=f"{chave}_esforco_{uso}",
                    )
            valores["CLAUDE_MAX_CHAMADAS_AUDITORIA"] = st.number_input(
                "Teto de chamadas ao plano por auditoria", min_value=1, max_value=200,
                value=provedor_ia.max_chamadas_auditoria(), step=5, key=f"{chave}_teto",
                help=(
                    "Protege o limite do plano: ao chegar no teto (ou se o limite do plano acabar), a auditoria "
                    "para e os produtos restantes são analisados na próxima execução, sem repetir os concluídos."
                ),
            )
            st.caption(
                "Recomendado para o plano Pro: **Sonnet** em tudo, raciocínio **Alto** só no diagnóstico de 30 dias. "
                "**Opus** dá pareceres mais profundos, mas consome o limite bem mais rápido. "
                "Ao trocar de motor ou de modelo, cada produto é reanalisado uma vez na próxima auditoria."
            )
        else:
            st.caption(
                f"Modelos da API OpenAI (CHAVES_DADOS.env): 7 dias `{config.OPENAI_MODEL_7D}` · "
                f"30 dias `{config.OPENAI_MODEL_30D}` · chat `{config.OPENAI_MODEL_CHAT}`. "
                "Cobrado por token na sua conta OpenAI."
            )
            if not config.OPENAI_API_KEY or config.OPENAI_API_KEY.lower().startswith("sua_chave"):
                st.warning("OPENAI_API_KEY não está configurada no CHAVES_DADOS.env.")

        col_salvar, col_testar = st.columns(2)
        if col_salvar.button("💾 Salvar motor de IA", type="primary", key=f"{chave}_salvar", use_container_width=True):
            provedor_ia.salvar_configuracao({k: str(v) for k, v in valores.items()})
            st.session_state[f"{chave}_salvo"] = True
            st.rerun()
        if escolha == "claude_code" and col_testar.button(
            "🔌 Testar resposta do Claude", key=f"{chave}_testar", use_container_width=True,
            help="Faz uma pergunta curtíssima com a configuração SALVA (modelo do chat).",
        ):
            with st.spinner("Perguntando ao Claude..."):
                try:
                    resposta = provedor_ia.testar_claude()
                    tokens = f"{resposta.tokens_entrada + resposta.tokens_saida:,}".replace(",", ".")
                    st.success(f"{resposta.texto}  \n`{resposta.modelo}` · {tokens} tokens do plano")
                except provedor_ia.ErroProvedorIA as exc:
                    st.error(str(exc))
