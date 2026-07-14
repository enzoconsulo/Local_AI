"""
cerebro/atuador.py
==================
Execução de ações aprovadas na API Shopee e registro no diário de bordo
(log_acoes_shopee), sempre vinculando a ação à execução analítica de origem
para que a avaliação previsto vs. observado feche o ciclo de aprendizado.
"""

import json

from loguru import logger

from utils.db_pool import get_connection
from utils.shopee_core import (
    atualizar_preco_shopee,
    criar_promocao_shopee,
    criar_combo_shopee,
    verificar_status_promocao,
)

__all__ = ["salvar_log_acao", "processar_acao_api", "verificar_status_promocao"]


def salvar_log_acao(
    item_id: int,
    model_id: int,
    tipo_acao: str,
    detalhe: str,
    impacto_json: dict,
    status: str,
    id_execucao_origem: str | None = None,
):
    # O vínculo com a execução analítica de origem chega por parâmetro: o núcleo
    # não lê st.session_state, então funciona em qualquer camada (UI ou worker).
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO log_acoes_shopee
                    (item_id, model_id, tipo_acao, detalhe_acao, impacto_projetado, status_api, id_execucao_origem)
                VALUES (%s, %s, %s, %s, %s, %s, %s::uuid)
                """,
                (item_id, model_id, tipo_acao, detalhe, json.dumps(impacto_json), status, id_execucao_origem or None),
            )


def processar_acao_api(
    acao: str, dados_var: dict, analise_var: dict, novo_preco: float,
    id_execucao_origem: str | None = None,
):
    """Isola a chamada da API da Shopee para manter o front-end responsivo."""
    duracao = analise_var.get("horas_duracao_promocao", 24)
    sucesso, msg = False, "Erro Desconhecido"

    try:
        if acao == "CRIAR_PROMOCAO":
            sucesso, msg = criar_promocao_shopee(dados_var["item_id"], dados_var["model_id"], novo_preco, duracao)
        elif acao in ("AUMENTAR_PRECO", "REDUZIR_PRECO"):
            sucesso, msg = atualizar_preco_shopee(dados_var["item_id"], dados_var["model_id"], novo_preco)
        elif acao == "CRIAR_COMBO":
            sucesso, msg = criar_combo_shopee(dados_var["item_id"], percentual_desconto=10)

        impacto_log = {
            "vendas_projetadas": analise_var.get("previsao_vendas_7d", 0),
            "lucro_projetado": analise_var.get("previsao_lucro_7d", 0),
            "estrategia": acao
        }

        if sucesso:
            salvar_log_acao(dados_var["item_id"], dados_var["model_id"], acao, f"Aprovado (Alvo: R$ {novo_preco:.2f})", impacto_log, "SUCESSO", id_execucao_origem)
            return True, msg
        else:
            salvar_log_acao(dados_var["item_id"], dados_var["model_id"], acao, f"Falha API (Alvo: R$ {novo_preco:.2f})", impacto_log, "ERRO_API", id_execucao_origem)
            return False, f"Falha na API: {msg}"
    except Exception as e:
        logger.error(f"Erro ao processar API Shopee: {e}")
        return False, f"Erro interno: {e}"
