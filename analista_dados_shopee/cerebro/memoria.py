"""
cerebro/memoria.py
==================
Memória analítica persistente do Cérebro (migrações 08–11):

  - Fingerprint determinístico dos fatos → cache semântico (não re-inferir
    SKU cujos fatos não mudaram = economia direta de tokens OpenAI).
  - Checkpoint durável por lote → auditoria sobrevive a quedas e retoma
    apenas os SKUs pendentes.
  - Avaliação de ações maduras → previsto vs. observado, sem afirmar
    causalidade.
  - Diário de bordo (log_acoes_shopee) vinculado à execução de origem.
"""

import hashlib
import json

import pandas as pd
import psycopg2.extras
from loguru import logger

from utils.db_pool import get_connection
from cerebro import config
from cerebro.config import memoizar_ttl
from cerebro.heuristicas import (
    calcular_dias_estoque,
    calcular_score_urgencia,
    classificar_confianca_evidencia,
)


# ══════════════════════════════════════════════════════════════════════════════
# DISPONIBILIDADE DAS MIGRAÇÕES (o app funciona degradado sem elas)
# ══════════════════════════════════════════════════════════════════════════════

@memoizar_ttl(60)
def _memoria_analitica_disponivel() -> bool:
    """Permite iniciar o app antes da migração 08, sem mascarar uma falha de banco."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('public.ia_execucoes_analiticas')")
                return cur.fetchone()[0] is not None
    except Exception as exc:
        logger.warning(f"Não foi possível verificar memória analítica: {exc}")
        return False


@memoizar_ttl(60)
def _cache_semantico_disponivel() -> bool:
    """Confirma a migração 10; sem ela, mantém persistência legada e desliga só o cache."""
    if not _memoria_analitica_disponivel():
        return False
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = 'ia_snapshots_variacao'
                          AND column_name = 'fingerprint_entrada'
                    )
                """)
                return bool(cur.fetchone()[0])
    except Exception as exc:
        logger.warning(f"Não foi possível verificar a migração do cache semântico: {exc}")
        return False


@memoizar_ttl(60)
def _checkpoint_analitico_disponivel() -> bool:
    """Exige as migrations 10 e 11 antes de ativar retomada por lote."""
    if not _cache_semantico_disponivel():
        return False
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = 'ia_execucoes_analiticas'
                          AND column_name = 'atualizado_em'
                    )
                """)
                return bool(cur.fetchone()[0])
    except Exception as exc:
        logger.warning(f"Checkpoint analítico indisponível: {exc}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# ENRIQUECIMENTO DO DOSSIÊ COM A MEMÓRIA
# ══════════════════════════════════════════════════════════════════════════════

def enriquecer_dossie_com_memoria(dossie: list[dict]) -> list[dict]:
    """Anexa a última estratégia mensal e a última avaliação de ação por variação."""
    if not dossie or not _memoria_analitica_disponivel():
        return dossie

    model_ids = [int(d["model_id"]) for d in dossie if d.get("model_id") is not None]
    if not model_ids:
        return dossie

    query = """
        WITH ultimo_mensal AS (
            SELECT DISTINCT ON (s.model_id)
                s.model_id, e.criado_em, s.metricas_observadas, s.previsoes,
                s.recomendacao, s.qualidade_evidencia
            FROM ia_snapshots_variacao s
            JOIN ia_execucoes_analiticas e ON e.id_execucao = s.id_execucao
            WHERE e.horizonte_dias = 30 AND e.status = 'CONCLUIDA'
              AND s.model_id = ANY(%s)
            ORDER BY s.model_id, e.criado_em DESC
        ), ultima_avaliacao AS (
            SELECT DISTINCT ON (a.model_id)
                a.model_id, a.avaliado_em, a.comparacao, a.status
            FROM ia_avaliacoes_acoes a
            WHERE a.model_id = ANY(%s)
            ORDER BY a.model_id, a.avaliado_em DESC
        )
        SELECT m.model_id, m.criado_em, m.metricas_observadas, m.previsoes,
               m.recomendacao, m.qualidade_evidencia,
               a.avaliado_em, a.comparacao, a.status AS status_avaliacao
        FROM ultimo_mensal m
        LEFT JOIN ultima_avaliacao a ON a.model_id = m.model_id;
    """
    memoria_por_modelo = {}
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(query, (model_ids, model_ids))
                for linha in cur.fetchall():
                    memoria_por_modelo[int(linha["model_id"])] = {
                        "ultima_analise_30d_em": linha["criado_em"].isoformat() if linha["criado_em"] else None,
                        "qualidade_evidencia": linha["qualidade_evidencia"],
                        "metricas_observadas": linha["metricas_observadas"] or {},
                        "previsoes": linha["previsoes"] or {},
                        "recomendacao": linha["recomendacao"] or {},
                        "ultima_avaliacao_em": linha["avaliado_em"].isoformat() if linha["avaliado_em"] else None,
                        "comparacao_ultima_acao": linha["comparacao"] or {},
                        "status_ultima_avaliacao": linha["status_avaliacao"],
                    }
    except Exception as exc:
        logger.warning(f"Memória analítica indisponível; auditoria seguirá sem histórico persistido: {exc}")
        return dossie

    for dados in dossie:
        memoria = memoria_por_modelo.get(int(dados["model_id"]))
        dados["MEMORIA_ESTRATEGICA_30D"] = memoria or None
    return dossie


# ══════════════════════════════════════════════════════════════════════════════
# FINGERPRINT (cache semântico)
# ══════════════════════════════════════════════════════════════════════════════

CAMPOS_FINGERPRINT_7D = {
    "item_id", "model_id", "nome_produto", "nome_variacao", "preco_atual",
    "custo_fab_real", "vendas_7d_reais", "tendencia_vendas_WoW_perc",
    "lucro_liquido_real_7d", "TRAFEGO_visitas_7d", "TRAFEGO_adicoes_carrinho_7d",
    "TRAFEGO_taxa_conversao_perc", "taxa_abandono_carrinho_perc",
    "ADS_gasto_7d", "ADS_roas_atual", "taxa_cancelamento_7d_perc",
    # Sinais de preço enviados no payload da IA: sem eles no fingerprint, uma
    # mudança de tendência de preço/elasticidade reutilizava análise antiga.
    "preco_tendencia_7d_perc", "elasticidade_preco_volume",
    "estoque_shopee_hoje", "LOGISTICA_capacidade_material_restante",
    "LOGISTICA_dias_estoque_restante", "previsao_vendas_7d", "previsao_lucro_7d",
    "TRAFEGO_ORG_impressoes_7d", "TRAFEGO_ORG_cliques_7d", "TRAFEGO_ORG_ctr_perc",
    "ADS_impressoes_7d", "ADS_cliques_7d", "ADS_ctr_perc", "ADS_acos_medio",
    "MEMORIA_ESTRATEGICA_30D", "historico_acoes_passadas",
    # Camada de correlação (v3): tudo o que chega ao modelo precisa estar no
    # fingerprint, ou uma mudança nesses fatos reutilizaria análise antiga.
    "FINANCEIRO_margem_unitaria_perc", "PORTFOLIO_share_variacao_30d_perc",
    "PORTFOLIO_curva_abc", "LOGISTICA_dias_estoque_shopee",
    "VENDAS_melhor_dia_semana", "VENDAS_share_melhor_dia_perc",
    "GEO_uf_top", "GEO_uf_top_share_perc",
    "CESTA_parceiro_top", "CESTA_pedidos_conjuntos_180d",
    "API_views_7d", "API_curtidas_7d",
    # Pós-venda (migração 17): promoção vigente e sinais enviados no payload.
    "PROMO_ativa_tipo", "PROMO_ativa_fim",
    "POSVENDA_recompra_perc_180d", "POSVENDA_preparo_atrasado_perc",
    "POSVENDA_devolucoes_90d",
}


def calcular_fingerprint_entrada(dados: dict, horizonte: str) -> str:
    """Hash determinístico dos fatos que realmente influenciam cada horizonte."""
    if horizonte == "30d":
        # A saída mensal anterior não é um fato novo e não pode invalidar o próprio cache.
        # Apenas a avaliação observada de ações passadas entra como nova evidência.
        selecionados = {k: v for k, v in dados.items() if k != "MEMORIA_ESTRATEGICA_30D"}
        memoria = dados.get("MEMORIA_ESTRATEGICA_30D") or {}
        selecionados["RESULTADO_OBSERVADO_ACAO"] = {
            "ultima_avaliacao_em": memoria.get("ultima_avaliacao_em"),
            "comparacao_ultima_acao": memoria.get("comparacao_ultima_acao"),
            "status_ultima_avaliacao": memoria.get("status_ultima_avaliacao"),
        }
    else:
        selecionados = {k: dados.get(k) for k in sorted(CAMPOS_FINGERPRINT_7D)}
    selecionados["CONFIGURACAO_IA"] = {
        "provedor": "openai",
        "modelo": config.modelo_para(horizonte),
        "reasoning_effort": config.reasoning_para(horizonte),
        "versao_prompt": config.VERSAO_PROMPT,
    }
    serializado = json.dumps(selecionados, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(serializado.encode("utf-8")).hexdigest()


# ══════════════════════════════════════════════════════════════════════════════
# SNAPSHOTS E PERSISTÊNCIA DE AUDITORIA
# ══════════════════════════════════════════════════════════════════════════════

CAMPOS_PREVISAO = (
    "previsao_vendas_7d", "previsao_lucro_7d", "previsao_vendas_30d", "previsao_lucro_30d",
)
CAMPOS_RECOMENDACAO = (
    "tipo_acao", "novo_preco_sugerido", "horas_duracao_promocao",
    "recomendacao_executiva", "plano_curto_prazo_7d", "plano_longo_prazo_30d",
    "analise_de_consequencias", "cluster_mercado", "relatorio_cfo_financas",
    "relatorio_cmo_marketing", "relatorio_coo_operacoes", "plano_acao_shopee",
    "elasticidade_preco_volume", "falha_modelo_externo", "analise_local",
)


def _montar_snapshots_analiticos(horizonte: str, resultados: list[dict]) -> list[tuple]:
    """Converte resultados em registros idempotentes de snapshot para uma mesma execução."""
    snapshots = []
    for resultado in resultados:
        dados = resultado.get("dados_atuais", {})
        if not dados.get("model_id") or not dados.get("item_id"):
            continue
        previsoes = {
            chave: resultado.get(chave, dados.get(chave))
            for chave in CAMPOS_PREVISAO
        }
        recomendacao = {
            chave: resultado.get(chave)
            for chave in CAMPOS_RECOMENDACAO
            if resultado.get(chave) is not None
        }
        snapshots.append((
            int(dados["item_id"]), int(dados["model_id"]),
            int(resultado.get("score_urgencia", 0) or 0),
            classificar_confianca_evidencia(dados)[0],
            resultado.get("tipo_acao", "MANTER"),
            calcular_fingerprint_entrada(dados, horizonte),
            json.dumps(dados, ensure_ascii=False),
            json.dumps(previsoes, ensure_ascii=False),
            json.dumps(recomendacao, ensure_ascii=False),
        ))
    return snapshots


def _resumo_execucao(horizonte: str, resultados: list[dict], checkpoint: bool = False) -> tuple[dict, dict]:
    """Cobertura e resumo executivo padronizados para qualquer forma de persistência."""
    horizonte_dias = config.horizonte_em_dias(horizonte)
    cobertura = {
        "variacoes": len(resultados),
        "dias_trafego_30d_mediana": int(pd.Series([
            r.get("dados_atuais", {}).get("COBERTURA_dias_trafego_30d", 0) for r in resultados
        ]).median() or 0),
    }
    resumo = {
        "acoes_recomendadas": sum(1 for r in resultados if r.get("tipo_acao") not in (None, "MANTER")),
        "falhas_modelo_externo": sum(1 for r in resultados if r.get("falha_modelo_externo")),
        "resultado_operacional_observado": round(sum(
            float(r.get("dados_atuais", {}).get(f"lucro_liquido_real_{horizonte_dias}d", 0) or 0)
            for r in resultados
        ), 2),
    }
    if checkpoint:
        resumo["checkpoint"] = True
    return cobertura, resumo


def persistir_auditoria_analitica(horizonte: str, resultados: list[dict], extras: dict | None = None) -> str | None:
    """Persiste uma auditoria e snapshots imutáveis sem duplicar os fatos do DW.
    Caminho legado, usado apenas quando o checkpoint (migração 11) não existe."""
    if not resultados or not _memoria_analitica_disponivel():
        return None

    horizonte_dias = config.horizonte_em_dias(horizonte)
    modelo_ia = f"openai:{config.modelo_para(horizonte)}"
    snapshots = _montar_snapshots_analiticos(horizonte, resultados)
    if not snapshots:
        return None

    cobertura, resumo = _resumo_execucao(horizonte, resultados)
    if extras:
        resumo.update(extras)
    status_execucao = "PARCIAL" if resumo["falhas_modelo_externo"] else "CONCLUIDA"
    cache_semantico = _cache_semantico_disponivel()
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO ia_execucoes_analiticas
                        (horizonte_dias, inicio_janela, fim_janela, modelo_ia, total_variacoes,
                         cobertura_dados, resumo_executivo, status)
                    VALUES (%s, CURRENT_DATE - (%s * INTERVAL '1 day'), CURRENT_DATE, %s, %s, %s::jsonb, %s::jsonb, %s)
                    RETURNING id_execucao;
                """, (
                    horizonte_dias, horizonte_dias, modelo_ia, len(snapshots),
                    json.dumps(cobertura), json.dumps(resumo), status_execucao,
                ))
                id_execucao = str(cur.fetchone()[0])
                if cache_semantico:
                    psycopg2.extras.execute_values(cur, """
                        INSERT INTO ia_snapshots_variacao
                            (id_execucao, item_id, model_id, score_urgencia, qualidade_evidencia,
                             tipo_acao_recomendada, fingerprint_entrada, metricas_observadas, previsoes, recomendacao)
                        VALUES %s
                    """, [
                        (id_execucao, *snapshot)
                        for snapshot in snapshots
                    ], template="(%s::uuid, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)")
                else:
                    psycopg2.extras.execute_values(cur, """
                        INSERT INTO ia_snapshots_variacao
                            (id_execucao, item_id, model_id, score_urgencia, qualidade_evidencia,
                             tipo_acao_recomendada, metricas_observadas, previsoes, recomendacao)
                        VALUES %s
                    """, [
                        (id_execucao, *snapshot[:5], *snapshot[6:])
                        for snapshot in snapshots
                    ], template="(%s::uuid, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)")
        return id_execucao
    except Exception as exc:
        logger.error(f"Falha ao persistir auditoria analítica: {exc}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# CHECKPOINT DURÁVEL (retomada de auditoria)
# ══════════════════════════════════════════════════════════════════════════════

def iniciar_ou_retomar_checkpoint(
    horizonte: str, total_variacoes: int, cobertura: dict,
) -> tuple[str | None, bool]:
    """Abre uma execução durável ou retoma a execução incompleta da janela corrente."""
    if not _checkpoint_analitico_disponivel():
        return None, False
    horizonte_dias = config.horizonte_em_dias(horizonte)
    modelo_ia = f"openai:{config.modelo_para(horizonte)}"
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Não retoma uma janela móvel expirada; preserva seus lotes válidos como parcial.
                cur.execute("""
                    UPDATE ia_execucoes_analiticas
                    SET status = 'PARCIAL',
                        resumo_executivo = COALESCE(resumo_executivo, '{}'::jsonb)
                            || jsonb_build_object('motivo_parcial', 'Janela expirada antes da conclusão'),
                        atualizado_em = CURRENT_TIMESTAMP
                    WHERE horizonte_dias = %s
                      AND fim_janela < CURRENT_DATE
                      AND status = 'EM_ANDAMENTO';
                """, (horizonte_dias,))
                cur.execute("""
                    SELECT id_execucao
                    FROM ia_execucoes_analiticas
                    WHERE horizonte_dias = %s
                      AND fim_janela = CURRENT_DATE
                      AND status = 'EM_ANDAMENTO'
                    ORDER BY atualizado_em DESC
                    LIMIT 1;
                """, (horizonte_dias,))
                existente = cur.fetchone()
                if existente:
                    id_execucao = str(existente[0])
                    cur.execute("""
                        UPDATE ia_execucoes_analiticas
                        SET total_variacoes = %s,
                            modelo_ia = %s,
                            cobertura_dados = %s::jsonb,
                            atualizado_em = CURRENT_TIMESTAMP
                        WHERE id_execucao = %s::uuid;
                    """, (total_variacoes, modelo_ia, json.dumps(cobertura), id_execucao))
                    retomada = True
                else:
                    cur.execute("""
                        INSERT INTO ia_execucoes_analiticas
                            (horizonte_dias, inicio_janela, fim_janela, modelo_ia, total_variacoes,
                             cobertura_dados, resumo_executivo, status, atualizado_em)
                        VALUES (
                            %s, CURRENT_DATE - (%s * INTERVAL '1 day'), CURRENT_DATE, %s, %s,
                            %s::jsonb, %s::jsonb, 'EM_ANDAMENTO', CURRENT_TIMESTAMP
                        )
                        RETURNING id_execucao;
                    """, (
                        horizonte_dias, horizonte_dias, modelo_ia, total_variacoes,
                        json.dumps(cobertura), json.dumps({"checkpoint": True}),
                    ))
                    id_execucao = str(cur.fetchone()[0])
                    retomada = False
        return id_execucao, retomada
    except Exception as exc:
        logger.error(f"Não foi possível abrir checkpoint analítico: {exc}")
        return None, False


def persistir_lote_no_checkpoint(id_execucao: str, horizonte: str, resultados: list[dict]) -> bool:
    """Confirma cada lote em transação própria; uma queda não apaga lotes anteriores."""
    snapshots = _montar_snapshots_analiticos(horizonte, resultados)
    if not snapshots:
        return True
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, """
                    INSERT INTO ia_snapshots_variacao
                        (id_execucao, item_id, model_id, score_urgencia, qualidade_evidencia,
                         tipo_acao_recomendada, fingerprint_entrada, metricas_observadas, previsoes, recomendacao)
                    VALUES %s
                    ON CONFLICT (id_execucao, model_id) DO UPDATE SET
                        item_id = EXCLUDED.item_id,
                        score_urgencia = EXCLUDED.score_urgencia,
                        qualidade_evidencia = EXCLUDED.qualidade_evidencia,
                        tipo_acao_recomendada = EXCLUDED.tipo_acao_recomendada,
                        fingerprint_entrada = EXCLUDED.fingerprint_entrada,
                        metricas_observadas = EXCLUDED.metricas_observadas,
                        previsoes = EXCLUDED.previsoes,
                        recomendacao = EXCLUDED.recomendacao,
                        criado_em = CURRENT_TIMESTAMP;
                """, [(id_execucao, *snapshot) for snapshot in snapshots],
                template="(%s::uuid, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)")
                cur.execute("""
                    UPDATE ia_execucoes_analiticas
                    SET atualizado_em = CURRENT_TIMESTAMP
                    WHERE id_execucao = %s::uuid;
                """, (id_execucao,))
        return True
    except Exception as exc:
        logger.error(f"Falha ao confirmar lote no checkpoint: {exc}")
        return False


def _resultado_de_snapshot(anterior, dados: dict, horizonte: str, retomado: bool) -> dict:
    return {
        **(anterior["previsoes"] or {}),
        **(anterior["recomendacao"] or {}),
        "item_id": int(dados["item_id"]),
        "model_id": int(dados["model_id"]),
        "dados_atuais": dados,
        "score_urgencia": calcular_score_urgencia(dados),
        "dias_estoque": calcular_dias_estoque(dados),
        "horizonte_auditoria": horizonte,
        "resultado_reutilizado": not retomado,
        "resultado_retomado": retomado,
        "id_execucao_analitica": str(anterior["id_execucao"]),
    }


def separar_resultados_do_checkpoint(
    id_execucao: str, horizonte: str, dossie: list[dict],
    aceitar_analise_local: bool = True,
) -> tuple[list[dict], list[dict]]:
    """Recupera somente snapshots do checkpoint ainda compatíveis com os fatos atuais.

    Com aceitar_analise_local=False (auditoria completa solicitada), pareceres
    determinísticos do modo econômico não são reutilizados: o usuário pediu IA.
    """
    if not id_execucao or not dossie:
        return [], dossie
    entradas = [
        {"model_id": int(d["model_id"]), "fingerprint_entrada": calcular_fingerprint_entrada(d, horizonte)}
        for d in dossie
    ]
    filtro_local = "" if aceitar_analise_local else \
        "AND COALESCE((s.recomendacao->>'analise_local')::boolean, FALSE) = FALSE"
    query = f"""
        WITH entradas AS (
            SELECT x.model_id, x.fingerprint_entrada
            FROM jsonb_to_recordset(%s::jsonb)
                AS x(model_id BIGINT, fingerprint_entrada TEXT)
        )
        SELECT s.id_execucao, s.model_id, s.previsoes, s.recomendacao
        FROM ia_snapshots_variacao s
        JOIN entradas i
          ON i.model_id = s.model_id
         AND i.fingerprint_entrada::CHAR(64) = s.fingerprint_entrada
        WHERE s.id_execucao = %s::uuid
          AND COALESCE((s.recomendacao->>'falha_modelo_externo')::boolean, FALSE) = FALSE
          {filtro_local};
    """
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(query, (json.dumps(entradas), id_execucao))
                anteriores = {int(r["model_id"]): r for r in cur.fetchall()}
    except Exception as exc:
        logger.warning(f"Não foi possível recuperar checkpoint: {exc}")
        return [], dossie

    retomados, pendentes = [], []
    for dados in dossie:
        anterior = anteriores.get(int(dados["model_id"]))
        if anterior:
            retomados.append(_resultado_de_snapshot(anterior, dados, horizonte, retomado=True))
        else:
            pendentes.append(dados)
    return retomados, pendentes


def finalizar_checkpoint(
    id_execucao: str, horizonte: str, resultados: list[dict], total_esperado: int,
    extras: dict | None = None,
) -> bool:
    """Fecha a execução apenas após validar cobertura e preserva PARCIAL quando necessário."""
    cobertura, resumo = _resumo_execucao(horizonte, resultados, checkpoint=True)
    if extras:
        resumo.update(extras)
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM ia_snapshots_variacao WHERE id_execucao = %s::uuid", (id_execucao,))
                total_persistido = int(cur.fetchone()[0])
                status = (
                    "CONCLUIDA"
                    if total_persistido >= total_esperado and not resumo["falhas_modelo_externo"]
                    else "PARCIAL"
                )
                cur.execute("""
                    UPDATE ia_execucoes_analiticas
                    SET total_variacoes = %s,
                        cobertura_dados = %s::jsonb,
                        resumo_executivo = %s::jsonb,
                        status = %s,
                        atualizado_em = CURRENT_TIMESTAMP
                    WHERE id_execucao = %s::uuid;
                """, (
                    total_esperado, json.dumps(cobertura), json.dumps(resumo), status, id_execucao,
                ))
        return status == "CONCLUIDA"
    except Exception as exc:
        logger.error(f"Falha ao finalizar checkpoint: {exc}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# CACHE SEMÂNTICO ENTRE EXECUÇÕES
# ══════════════════════════════════════════════════════════════════════════════

def separar_resultados_reutilizaveis(
    horizonte: str, dossie: list[dict], aceitar_analise_local: bool = True,
) -> tuple[list[dict], list[dict]]:
    """Reutiliza inferência recente somente quando o fingerprint dos fatos é idêntico."""
    if not dossie or not _cache_semantico_disponivel():
        return [], dossie
    dias_cache = 1 if horizonte == "7d" else 7
    entradas = [
        {
            "model_id": int(dados["model_id"]),
            "fingerprint_entrada": calcular_fingerprint_entrada(dados, horizonte),
        }
        for dados in dossie
    ]
    filtro_local = "" if aceitar_analise_local else \
        "AND COALESCE((s.recomendacao->>'analise_local')::boolean, FALSE) = FALSE"
    query = f"""
        WITH entradas AS (
            SELECT x.model_id, x.fingerprint_entrada
            FROM jsonb_to_recordset(%s::jsonb)
                AS x(model_id BIGINT, fingerprint_entrada TEXT)
        )
        SELECT DISTINCT ON (s.model_id)
            s.id_execucao, s.model_id, s.fingerprint_entrada, s.previsoes, s.recomendacao
        FROM ia_snapshots_variacao s
        JOIN ia_execucoes_analiticas e ON e.id_execucao = s.id_execucao
        JOIN entradas i
          ON i.model_id = s.model_id
         AND i.fingerprint_entrada::CHAR(64) = s.fingerprint_entrada
        WHERE e.horizonte_dias = %s AND e.status IN ('CONCLUIDA', 'PARCIAL')
          AND e.criado_em >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')
          AND s.fingerprint_entrada IS NOT NULL
          AND COALESCE((s.recomendacao->>'falha_modelo_externo')::boolean, FALSE) = FALSE
          {filtro_local}
        ORDER BY s.model_id, e.criado_em DESC;
    """
    anteriores = {}
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(query, (json.dumps(entradas), config.horizonte_em_dias(horizonte), dias_cache))
                anteriores = {int(r["model_id"]): r for r in cur.fetchall()}
    except Exception as exc:
        logger.warning(f"Cache semântico indisponível; todos os SKUs serão analisados: {exc}")
        return [], dossie

    reutilizados, pendentes = [], []
    for dados in dossie:
        anterior = anteriores.get(int(dados["model_id"]))
        if not anterior:
            pendentes.append(dados)
            continue
        reutilizados.append(_resultado_de_snapshot(anterior, dados, horizonte, retomado=False))
    return reutilizados, pendentes


# ══════════════════════════════════════════════════════════════════════════════
# AVALIAÇÃO DE AÇÕES MADURAS (previsto vs. observado)
# ══════════════════════════════════════════════════════════════════════════════

def avaliar_acoes_maduras(dossie_atual: list[dict]) -> int:
    """Compara cada ação madura à JANELA EXATA de 7 dias após a aplicação.

    Antes, o "observado" usava a janela corrente de 7 dias: se a auditoria
    ficasse semanas sem rodar, media um período sem relação com a ação. Agora
    as vendas observadas vêm de vw_vendas_diarias_variacao no intervalo
    [aplicação, aplicação+7d]. Registra associação, não causalidade.
    """
    if not dossie_atual or not _memoria_analitica_disponivel():
        return 0
    atuais = {int(d["model_id"]): d for d in dossie_atual if d.get("model_id") is not None}
    if not atuais:
        return 0

    # LEFT JOIN no snapshot: ações registradas sem execução de origem (sessão
    # restaurada de cache antigo, ações da Visão Central) também maturam — o
    # baseline delas fica vazio, mas o observado da janela pós-ação é medido.
    query = """
        SELECT l.id_log, l.id_execucao_origem, l.item_id, l.model_id, l.data_aplicacao,
               l.impacto_projetado, s.metricas_observadas
        FROM log_acoes_shopee l
        LEFT JOIN ia_snapshots_variacao s
          ON s.id_execucao = l.id_execucao_origem AND s.model_id = l.model_id
        LEFT JOIN ia_avaliacoes_acoes a ON a.id_log = l.id_log
        WHERE l.status_api = 'SUCESSO'
          AND l.model_id = ANY(%s)
          AND l.data_aplicacao <= CURRENT_TIMESTAMP - INTERVAL '7 days'
          AND a.id_log IS NULL;
    """
    avaliadas = 0
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(query, (list(atuais),))
                pendentes = cur.fetchall()
                for acao in pendentes:
                    atual = atuais[int(acao["model_id"])]
                    baseline = acao["metricas_observadas"] or {}
                    previsto = acao["impacto_projetado"] or {}

                    # Vendas na janela exata pós-ação (fonte: view da migração 12)
                    cur.execute("""
                        SELECT
                            COALESCE(SUM(unidades_vendidas), 0)               AS vendas_janela,
                            COALESCE(SUM(receita_bruta), 0)                   AS receita_bruta_janela,
                            COUNT(*) FILTER (WHERE unidades_vendidas > 0)     AS dias_com_venda_janela
                        FROM vw_vendas_diarias_variacao
                        WHERE model_id = %s
                          AND data >  %s::date
                          AND data <= %s::date + 7;
                    """, (acao["model_id"], acao["data_aplicacao"], acao["data_aplicacao"]))
                    janela = cur.fetchone()
                    vendas_janela = int(janela["vendas_janela"] or 0)

                    observado = {
                        "vendas_7d_pos_acao": vendas_janela,
                        "receita_bruta_7d_pos_acao": round(float(janela["receita_bruta_janela"] or 0), 2),
                        "dias_com_venda_pos_acao": int(janela["dias_com_venda_janela"] or 0),
                        # Lucro/conversão exatos da janela exigiriam rateio histórico de
                        # escrow e tráfego; usamos o estado corrente como aproximação declarada.
                        "lucro_7d_corrente_aprox": atual.get("lucro_liquido_real_7d"),
                        "conversao_7d_corrente_aprox": atual.get("TRAFEGO_taxa_conversao_perc"),
                    }
                    comparacao = {
                        "delta_vendas_vs_baseline": vendas_janela - (baseline.get("vendas_7d_reais", 0) or 0),
                        "delta_lucro_vs_baseline": round((atual.get("lucro_liquido_real_7d", 0) or 0) - (baseline.get("lucro_liquido_real_7d", 0) or 0), 2),
                        "delta_vendas_vs_previsto": vendas_janela - (previsto.get("vendas_projetadas", 0) or 0),
                        "delta_lucro_vs_previsto": round((atual.get("lucro_liquido_real_7d", 0) or 0) - (previsto.get("lucro_projetado", 0) or 0), 2),
                    }
                    status = "DADOS_INSUFICIENTES" if vendas_janela == 0 and atual.get("TRAFEGO_visitas_7d", 0) in (None, 0) else "AVALIADA"
                    cur.execute("""
                        INSERT INTO ia_avaliacoes_acoes
                            (id_log, id_execucao_origem, item_id, model_id, horizonte_observacao_dias,
                             data_inicio_observacao, data_fim_observacao, baseline, previsto, observado, comparacao, status)
                        VALUES (%s, %s::uuid, %s, %s, 7, %s, %s + INTERVAL '7 days',
                                %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s)
                    """, (
                        acao["id_log"],
                        str(acao["id_execucao_origem"]) if acao["id_execucao_origem"] else None,
                        acao["item_id"], acao["model_id"],
                        acao["data_aplicacao"], acao["data_aplicacao"],
                        json.dumps(baseline), json.dumps(previsto), json.dumps(observado), json.dumps(comparacao), status
                    ))
                    avaliadas += 1
    except Exception as exc:
        logger.error(f"Falha ao avaliar ações maduras: {exc}")
    return avaliadas
