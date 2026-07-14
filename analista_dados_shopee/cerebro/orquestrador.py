"""
cerebro/orquestrador.py
=======================
Fluxo completo de uma auditoria por horizonte:

    dossiê → avaliação de ações maduras → checkpoint/retomada →
    cache semântico → lotes OpenAI (só os SKUs pendentes) →
    finalização + persistência em banco e em disco.

A ordem das economias importa: primeiro o checkpoint da janela corrente,
depois o cache semântico entre execuções, e só então a API paga.
"""

import json
import os
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
from loguru import logger

from utils.db_pool import get_connection
from cerebro import config, memoria, motor_ia
from cerebro.dossie import gerar_dossie_produtos_com_memoria
from cerebro.memoria import enriquecer_dossie_com_memoria

# Idade máxima tolerada de cada fonte antes de alertar que a auditoria
# rodará sobre dados velhos (previsão precisa exige insumo fresco).
LIMITES_FRESCOR = {
    "PEDIDOS": timedelta(hours=36),
    "TRAFEGO_ORG": timedelta(days=7),
    "ADS_AVANCADO": timedelta(days=7),
}


def verificar_frescor_dados(status_boot) -> list[str]:
    """Alerta (sem bloquear) quando alguma fonte do DW está velha ou ausente.

    Uma auditoria sobre dados defasados produz previsões com aparência de
    precisão e base podre — o aviso vai para o log da execução e para a tela.
    """
    avisos = []
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT modulo, MAX(data_fim_coleta)
                    FROM sys_controle_sync
                    WHERE status = 'SUCESSO'
                    GROUP BY modulo;
                """)
                ultimas = {modulo: data for modulo, data in cur.fetchall()}
        agora = datetime.now()
        for modulo, limite in LIMITES_FRESCOR.items():
            ultima = ultimas.get(modulo)
            if ultima is None:
                avisos.append(f"{modulo}: nunca sincronizado.")
            elif agora - ultima > limite:
                idade_dias = (agora - ultima).days
                avisos.append(f"{modulo}: última sincronização há {idade_dias} dia(s) ({ultima:%d/%m %H:%M}).")
    except Exception as exc:
        logger.warning(f"Não foi possível verificar o frescor dos dados: {exc}")
        return []

    for aviso in avisos:
        status_boot.write(f"⚠️ Dado possivelmente defasado — {aviso} Considere sincronizar antes de decidir.")
    return avisos


def executar_auditoria_por_horizonte(horizonte: str, status_boot, modo_economico: bool = True) -> list[dict]:
    """Executa e persiste um único horizonte; 7d é recorrente, 30d é estratégico."""
    config.horizonte_em_dias(horizonte)  # valida o horizonte

    avisos_frescor = verificar_frescor_dados(status_boot)

    status_boot.write("Lendo Data Warehouse e consolidando métricas...")
    try:
        dossie = gerar_dossie_produtos_com_memoria()
    except config.MigracaoPendenteError as exc:
        st.error(str(exc))
        status_boot.update(label="Migração de banco pendente", state="error", expanded=True)
        st.stop()
    if not dossie:
        status_boot.update(label="Sem produtos ativos para auditar", state="error", expanded=True)
        st.stop()

    acoes_avaliadas = memoria.avaliar_acoes_maduras(dossie)
    if acoes_avaliadas:
        status_boot.write(f"Atualizando aprendizagem com {acoes_avaliadas} ação(ões) já maturadas...")
        dossie = enriquecer_dossie_com_memoria(dossie)

    descricao = "operacional de 7 dias" if horizonte == "7d" else "estratégica de 30 dias"
    cobertura_inicial = {
        "variacoes_esperadas": len(dossie),
        "dias_trafego_30d_mediana": int(pd.Series([
            d.get("COBERTURA_dias_trafego_30d", 0) for d in dossie
        ]).median() or 0),
    }
    id_checkpoint, _ = memoria.iniciar_ou_retomar_checkpoint(
        horizonte, len(dossie), cobertura_inicial,
    )

    # Em auditoria completa (modo_economico=False), pareceres locais antigos
    # não são reutilizados — o usuário pediu explicitamente análise de IA.
    retomados, dossie_a_verificar = (
        memoria.separar_resultados_do_checkpoint(
            id_checkpoint, horizonte, dossie, aceitar_analise_local=modo_economico,
        )
        if id_checkpoint else ([], dossie)
    )
    reutilizados, pendentes = memoria.separar_resultados_reutilizaveis(
        horizonte, dossie_a_verificar, aceitar_analise_local=modo_economico,
    )
    resultados_iniciais = retomados + reutilizados

    if id_checkpoint and resultados_iniciais:
        memoria.persistir_lote_no_checkpoint(id_checkpoint, horizonte, resultados_iniciais)
    if retomados:
        status_boot.write(
            f"Retomada segura: {len(retomados)} variação(ões) já concluídas foram restauradas do checkpoint."
        )
    if reutilizados:
        status_boot.write(
            f"Economia de inferência: {len(reutilizados)} variação(ões) sem mudança reutilizadas com segurança."
        )

    telemetria = {
        "chamadas": 0, "prompt_tokens": 0, "completion_tokens": 0,
        "lotes_divididos": 0, "lotes_falhos": 0, "skus_analise_local": 0,
    }

    novos_resultados = []
    if pendentes:
        status_boot.write(
            f"Enviando somente {len(pendentes)} de {len(dossie)} variações para análise {descricao}..."
        )
        config_ok, motivo_config = motor_ia.configuracao_openai_valida()
        if not config_ok:
            st.error(motivo_config)
            status_boot.update(label="Configuração OpenAI pendente", state="error", expanded=True)
            st.stop()

        def confirmar_lote(lote: list[dict]) -> None:
            if id_checkpoint and not memoria.persistir_lote_no_checkpoint(id_checkpoint, horizonte, lote):
                raise RuntimeError("Falha ao confirmar o lote no checkpoint; a execução poderá ser retomada.")

        # O núcleo (motor_ia) não conhece Streamlit: a barra de progresso é
        # injetada daqui, e o mesmo pipeline roda em CLI/testes/página 4.
        barra_progresso = st.progress(0.0, text="🚀 Preparando lotes para a API OpenAI...")
        try:
            novos_resultados = motor_ia.processar_em_lotes(
                pendentes,
                horizonte=horizonte,
                ao_concluir_lote=confirmar_lote if id_checkpoint else None,
                modo_economico=modo_economico,
                telemetria=telemetria,
                ao_progresso=lambda fracao, texto: barra_progresso.progress(fracao, text=texto),
            )
        finally:
            barra_progresso.empty()
    else:
        status_boot.write("Nenhum fato mudou; nenhuma chamada à OpenAI foi necessária.")

    resultados = resultados_iniciais + novos_resultados
    resultados.sort(key=lambda r: int(r.get("score_urgencia", 0) or 0), reverse=True)
    for resultado in resultados:
        resultado["horizonte_auditoria"] = horizonte

    # Telemetria de custo: fica no resumo da execução (banco) e na tela.
    extras_resumo = {
        "telemetria_ia": {
            **telemetria,
            "modelo": config.modelo_para(horizonte),
            "reasoning_effort": config.reasoning_para(horizonte),
            "modo_economico": modo_economico,
            "skus_retomados": len(retomados),
            "skus_cache_semantico": len(reutilizados),
        },
        "avisos_frescor": avisos_frescor,
    }
    if telemetria["chamadas"]:
        status_boot.write(
            f"💰 Custo desta auditoria: {telemetria['chamadas']} chamada(s) à OpenAI, "
            f"{telemetria['prompt_tokens']:,} tokens de entrada e {telemetria['completion_tokens']:,} de saída."
        )
    if telemetria["skus_analise_local"]:
        status_boot.write(
            f"💸 Modo econômico: {telemetria['skus_analise_local']} SKU(s) de evidência baixa "
            "resolvidos localmente, sem custo de IA."
        )
    if telemetria["lotes_falhos"]:
        status_boot.write(
            f"⚠️ {telemetria['lotes_falhos']} lote(s) não concluíram na IA e receberam fallback; "
            "eles serão reanalisados automaticamente na próxima execução."
        )

    if id_checkpoint:
        memoria.finalizar_checkpoint(id_checkpoint, horizonte, resultados, len(dossie), extras=extras_resumo)
        id_execucao = id_checkpoint
    else:
        id_execucao = memoria.persistir_auditoria_analitica(horizonte, resultados, extras=extras_resumo)
    if id_execucao:
        st.session_state.id_execucao_analitica = id_execucao
        for resultado in resultados:
            resultado["id_execucao_analitica"] = id_execucao

    salvar_cache_em_disco(horizonte, resultados)
    return resultados


def executar_analise_7_dias(status_boot) -> list[dict]:
    """Fluxo recorrente: decisão operacional baseada exclusivamente nos sinais de 7 dias."""
    return executar_auditoria_por_horizonte("7d", status_boot)


def executar_analise_30_dias(status_boot) -> list[dict]:
    """Fluxo estratégico: diagnóstico mensal completo para a primeira execução e revisões ocasionais."""
    return executar_auditoria_por_horizonte("30d", status_boot)


# ══════════════════════════════════════════════════════════════════════════════
# CACHE EM DISCO (sobrevive a F5 e reinício do app)
# ══════════════════════════════════════════════════════════════════════════════

def salvar_cache_em_disco(horizonte: str, resultados: list[dict]) -> None:
    destino = config.CACHE_AUDITORIA_7D if horizonte == "7d" else config.CACHE_AUDITORIA_30D
    try:
        with open(destino, "w", encoding="utf-8") as arquivo:
            json.dump(resultados, arquivo, ensure_ascii=False, indent=4)
        # Mantém o arquivo legado atualizado para não quebrar instalações existentes.
        with open(config.CACHE_AUDITORIA, "w", encoding="utf-8") as arquivo:
            json.dump(resultados, arquivo, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Falha ao persistir cache de auditoria: {e}")


def carregar_ultima_auditoria() -> tuple[list[dict], str | None, str | None]:
    """Restaura a auditoria mais recente do disco.

    Retorna (analises, horizonte, id_execucao). Prioriza o cache modificado
    há menos tempo entre 7d, 30d e o arquivo legado.
    """
    caches_disponiveis = [
        (config.CACHE_AUDITORIA_7D, "7d"),
        (config.CACHE_AUDITORIA_30D, "30d"),
        (config.CACHE_AUDITORIA, None),
    ]
    caches_existentes = [c for c in caches_disponiveis if c[0].exists()]
    caches_ordenados = sorted(caches_existentes, key=lambda x: os.path.getmtime(x[0]), reverse=True)

    for cache, horizonte in caches_ordenados:
        try:
            with open(cache, "r", encoding="utf-8") as f:
                analises = json.load(f)

            horizonte_final = horizonte or (
                analises[0].get("horizonte_auditoria") if analises else None
            )
            id_execucao = analises[0].get("id_execucao_analitica") if analises else None
            return analises, horizonte_final, id_execucao
        except Exception:
            continue
    return [], None, None
