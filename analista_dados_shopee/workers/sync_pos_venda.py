"""
workers/sync_pos_venda.py
=========================
Sincronizações 100% via API descobertas na sondagem de 18/07/2026 (todas
confirmadas FUNCIONANDO para este app in-house):

1. ENRIQUECIMENTO de pedidos históricos — lotes de 50 no get_order_detail para
   preencher comprador, pay/ship_by/pickup, frete real e UF em pedidos gravados
   antes destes campos existirem (backfill barato: ~7 chamadas para 350 pedidos).
2. RASTREIO (get_tracking_info) — status logístico e momento da entrega de
   pedidos recentes ainda não entregues; alimenta o tempo real de entrega.
3. DEVOLUÇÕES (get_return_list) — motivo e itens de cada devolução: sinal de
   qualidade por produto que a planilha só mostra agregado.
4. PROMOÇÕES (4 famílias) — desconto, combo, add-on e flash sale com os itens
   cobertos: sem isso, queda de preço promocional contamina a elasticidade.

Tudo idempotente (upserts) e registrado em sys_controle_sync como POS_VENDA.
"""

import json
import sys
from datetime import datetime, date
from pathlib import Path

import psycopg2.extras
from loguru import logger

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from utils.db_pool import get_connection
from utils.shopee_core import (
    chamar_shopee_api,
    listar_devolucoes,
    listar_promocoes_loja,
    obter_rastreio_pedido,
)
from workers.importar_planilhas import registrar_sincronizacao
from workers.sync_pedidos import CAMPOS_OPCIONAIS_PEDIDO, _pedido_do_detalhe

# Rastreiam-se pedidos desta janela que ainda não constam como entregues; o
# teto por execução limita o tempo da 1ª rodada (os demais entram na próxima).
JANELA_RASTREIO_DIAS = 90
MAX_RASTREIOS_POR_EXECUCAO = 150


def _ts(epoch):
    try:
        epoch = int(epoch or 0)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(epoch) if epoch > 0 else None


# ══════════════════════════════════════════════════════════════════════════════
# 1. ENRIQUECIMENTO DE PEDIDOS HISTÓRICOS (backfill em lotes de 50)
# ══════════════════════════════════════════════════════════════════════════════

def enriquecer_pedidos_existentes() -> tuple[int, str]:
    """Preenche os campos pós-venda dos pedidos que ainda não os têm.

    Depois que o sync_pedidos passou a capturar os campos na origem, esta
    função tende a não encontrar nada — ela existe para o estoque histórico.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT order_sn FROM fato_pedidos_venda
                WHERE pay_time IS NULL
                ORDER BY data_hora_criacao DESC
            """)
            pendentes = [r[0] for r in cur.fetchall()]

    if not pendentes:
        return 0, "Todos os pedidos já têm os campos pós-venda."

    logger.info(f"Enriquecendo {len(pendentes)} pedido(s) histórico(s) em lotes de 50...")
    atualizados = 0
    for inicio in range(0, len(pendentes), 50):
        lote = pendentes[inicio:inicio + 50]
        resp = chamar_shopee_api("/api/v2/order/get_order_detail", params={
            "order_sn_list": ",".join(lote),
            "response_optional_fields": CAMPOS_OPCIONAIS_PEDIDO,
        })
        if not resp or "order_list" not in resp:
            logger.warning(f"Lote de enriquecimento sem resposta ({inicio}-{inicio + len(lote)}); seguindo.")
            continue
        pedidos = [_pedido_do_detalhe(order) for order in resp["order_list"]]
        with get_connection() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, """
                    UPDATE fato_pedidos_venda AS f SET
                        buyer_user_id = COALESCE(d.buyer_user_id::BIGINT, f.buyer_user_id),
                        buyer_username = COALESCE(d.buyer_username, f.buyer_username),
                        pay_time = COALESCE(d.pay_time::TIMESTAMP, f.pay_time),
                        ship_by_date = COALESCE(d.ship_by_date::TIMESTAMP, f.ship_by_date),
                        pickup_done_time = COALESCE(d.pickup_done_time::TIMESTAMP, f.pickup_done_time),
                        frete_real = COALESCE(d.frete_real::DECIMAL, f.frete_real),
                        shipping_carrier = COALESCE(d.shipping_carrier, f.shipping_carrier),
                        uf_destino = COALESCE(d.uf_destino, f.uf_destino),
                        status_pedido = COALESCE(d.status_pedido, f.status_pedido)
                    FROM (VALUES %s) AS d(order_sn, buyer_user_id, buyer_username, pay_time,
                                          ship_by_date, pickup_done_time, frete_real,
                                          shipping_carrier, uf_destino, status_pedido)
                    WHERE f.order_sn = d.order_sn;
                """, [
                    (p["order_sn"], p.get("buyer_user_id"), p.get("buyer_username"),
                     p.get("pay_time"), p.get("ship_by_date"), p.get("pickup_done_time"),
                     p.get("frete_real"), p.get("shipping_carrier"), p.get("uf_destino"),
                     p.get("status_pedido"))
                    for p in pedidos
                ])
        atualizados += len(pedidos)

    logger.success(f"Enriquecimento concluído: {atualizados} pedido(s) atualizados.")
    return atualizados, "Sucesso"


# ══════════════════════════════════════════════════════════════════════════════
# 2. RASTREIO (entrega real por pedido)
# ══════════════════════════════════════════════════════════════════════════════

def sincronizar_rastreio() -> tuple[int, str]:
    """Atualiza logistics_status/delivered_time dos pedidos recentes não entregues."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT order_sn FROM fato_pedidos_venda
                WHERE data_hora_criacao >= CURRENT_DATE - %s
                  AND status_pedido NOT IN ('CANCELLED', 'CANCELED', 'CANCELLED_BY_BUYER',
                                            'IN_CANCEL', 'UNPAID')
                  AND delivered_time IS NULL
                  AND pickup_done_time IS NOT NULL
                ORDER BY data_hora_criacao DESC
                LIMIT %s
            """, (JANELA_RASTREIO_DIAS, MAX_RASTREIOS_POR_EXECUCAO))
            pendentes = [r[0] for r in cur.fetchall()]

    if not pendentes:
        return 0, "Nenhum pedido recente aguardando confirmação de entrega."

    logger.info(f"Consultando rastreio de {len(pendentes)} pedido(s)...")
    atualizacoes = []
    for order_sn in pendentes:
        status_log, delivered = obter_rastreio_pedido(order_sn)
        if status_log or delivered:
            atualizacoes.append((order_sn, status_log, _ts(delivered)))

    if atualizacoes:
        with get_connection() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, """
                    UPDATE fato_pedidos_venda AS f SET
                        logistics_status = COALESCE(d.logistics_status, f.logistics_status),
                        delivered_time = COALESCE(d.delivered_time::TIMESTAMP, f.delivered_time)
                    FROM (VALUES %s) AS d(order_sn, logistics_status, delivered_time)
                    WHERE f.order_sn = d.order_sn;
                """, atualizacoes)
    logger.success(f"Rastreio: {len(atualizacoes)} pedido(s) atualizados.")
    return len(atualizacoes), "Sucesso"


# ══════════════════════════════════════════════════════════════════════════════
# 3. DEVOLUÇÕES
# ══════════════════════════════════════════════════════════════════════════════

def sincronizar_devolucoes() -> tuple[int, str]:
    """Upsert de todas as devoluções da loja (base pequena: janela completa)."""
    devolucoes = listar_devolucoes()
    if not devolucoes:
        return 0, "Nenhuma devolução registrada na Shopee."

    with get_connection() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, """
                INSERT INTO fato_devolucoes
                    (return_sn, order_sn, status, motivo, motivo_texto, valor_reembolso, criado_em_shopee, atualizado_em)
                VALUES %s
                ON CONFLICT (return_sn) DO UPDATE SET
                    status = EXCLUDED.status,
                    motivo = EXCLUDED.motivo,
                    motivo_texto = EXCLUDED.motivo_texto,
                    valor_reembolso = EXCLUDED.valor_reembolso,
                    atualizado_em = CURRENT_TIMESTAMP;
            """, [
                (d["return_sn"], d["order_sn"], d["status"], d["motivo"], d["motivo_texto"],
                 d["valor_reembolso"], _ts(d["criado_em"]))
                for d in devolucoes
            ], template="(%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)")

            itens = [
                (d["return_sn"], item_id, model_id, quantidade)
                for d in devolucoes
                for (item_id, model_id, quantidade) in d["itens"]
            ]
            if itens:
                psycopg2.extras.execute_values(cur, """
                    INSERT INTO map_devolucao_itens (return_sn, item_id, model_id, quantidade)
                    VALUES %s
                    ON CONFLICT (return_sn, item_id, model_id) DO UPDATE SET
                        quantidade = EXCLUDED.quantidade;
                """, itens)

    logger.success(f"Devoluções: {len(devolucoes)} registro(s) sincronizados.")
    return len(devolucoes), "Sucesso"


# ══════════════════════════════════════════════════════════════════════════════
# 4. PROMOÇÕES (4 famílias)
# ══════════════════════════════════════════════════════════════════════════════

def sincronizar_promocoes() -> tuple[int, str]:
    """Upsert das promoções da loja com os itens cobertos por cada uma."""
    promocoes = listar_promocoes_loja(incluir_itens=True)
    if not promocoes:
        return 0, "Nenhuma promoção encontrada na loja."

    with get_connection() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, """
                INSERT INTO fato_promocoes_shopee (tipo, id_promocao, nome, status, inicio, fim, atualizado_em)
                VALUES %s
                ON CONFLICT (tipo, id_promocao) DO UPDATE SET
                    nome = EXCLUDED.nome,
                    status = EXCLUDED.status,
                    inicio = EXCLUDED.inicio,
                    fim = EXCLUDED.fim,
                    atualizado_em = CURRENT_TIMESTAMP;
            """, [
                (p["tipo"], p["id_promocao"], p["nome"], p["status"],
                 _ts(p.get("inicio")), _ts(p.get("fim")))
                for p in promocoes
            ], template="(%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)")

            # Itens: replace por promoção (espelha a API; promo editada não
            # acumula itens que saíram dela)
            chaves = [{"tipo": p["tipo"], "id_promocao": p["id_promocao"]} for p in promocoes]
            cur.execute("""
                DELETE FROM map_promocao_itens
                WHERE (tipo, id_promocao) IN (SELECT x.tipo, x.id_promocao
                                              FROM jsonb_to_recordset(%s::jsonb)
                                              AS x(tipo TEXT, id_promocao BIGINT));
            """, (json.dumps(chaves),))
            itens = [
                (p["tipo"], p["id_promocao"], item_id, model_id, preco)
                for p in promocoes
                for (item_id, model_id, preco) in (p.get("itens") or [])
            ]
            if itens:
                psycopg2.extras.execute_values(cur, """
                    INSERT INTO map_promocao_itens (tipo, id_promocao, item_id, model_id, preco_promocional)
                    VALUES %s
                    ON CONFLICT (tipo, id_promocao, item_id, model_id) DO UPDATE SET
                        preco_promocional = EXCLUDED.preco_promocional;
                """, itens)

    vigentes = sum(1 for p in promocoes if p["status"] == "ongoing")
    logger.success(f"Promoções: {len(promocoes)} sincronizadas ({vigentes} vigentes).")
    return len(promocoes), "Sucesso"


# ══════════════════════════════════════════════════════════════════════════════
# ORQUESTRAÇÃO (função exportada para a página 2)
# ══════════════════════════════════════════════════════════════════════════════

def sincronizar_pos_venda(ao_progresso=None) -> dict:
    """Executa as 4 sincronizações e devolve um resumo para a interface.

    Falha em uma etapa não impede as demais — cada uma é independente e o
    resumo aponta o que precisa de atenção.
    """
    def _notificar(fracao, texto):
        if ao_progresso is not None:
            try:
                ao_progresso(fracao, texto)
            except Exception:
                pass

    resumo = {}
    etapas = (
        ("enriquecimento", "Enriquecendo pedidos históricos...", enriquecer_pedidos_existentes),
        ("rastreio", "Consultando rastreio das entregas...", sincronizar_rastreio),
        ("devolucoes", "Sincronizando devoluções...", sincronizar_devolucoes),
        ("promocoes", "Sincronizando promoções da loja...", sincronizar_promocoes),
    )
    for indice, (chave, texto, funcao) in enumerate(etapas):
        _notificar(indice / len(etapas), texto)
        try:
            quantidade, msg = funcao()
            resumo[chave] = {"quantidade": quantidade, "msg": msg, "ok": True}
        except Exception as exc:
            logger.error(f"Etapa de pós-venda '{chave}' falhou: {exc}")
            resumo[chave] = {"quantidade": 0, "msg": str(exc), "ok": False}
    _notificar(1.0, "Pós-venda sincronizado.")

    hoje = date.today()
    total = sum(e["quantidade"] for e in resumo.values())
    status = "SUCESSO" if all(e["ok"] for e in resumo.values()) else "ERRO"
    try:
        registrar_sincronizacao("POS_VENDA", hoje, hoje, status, total)
    except Exception as exc:
        logger.warning(f"Não foi possível registrar POS_VENDA em sys_controle_sync: {exc}")
    return resumo


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    resultado = sincronizar_pos_venda()
    for etapa, dados in resultado.items():
        print(f"{etapa}: {'OK' if dados['ok'] else 'FALHA'} — {dados['quantidade']} registro(s) — {dados['msg']}")
