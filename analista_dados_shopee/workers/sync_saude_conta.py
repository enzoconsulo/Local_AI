"""
workers/sync_saude_conta.py
===========================
Sincronizações leves 100% via API (sem planilha):

1. Saúde da conta (v2.account_health) — as métricas que decidem o ALCANCE
   orgânico da loja (envio atrasado, pedidos não cumpridos, pontos de
   penalidade). Snapshot diário gravado em fato_visao_geral_loja com
   fonte 'API_SAUDE_CONTA' para o Cérebro enxergar a tendência.

2. Métricas extras por item (v2.product.get_item_extra_info) — views,
   curtidas e vendas ACUMULADAS de cada produto. O snapshot diário em
   fato_metricas_produto_importadas (fonte 'API_EXTRA_INFO') permite
   calcular deltas (views de hoje = acumulado hoje − acumulado ontem),
   um proxy de tráfego que não depende de exportar planilha.

Ambos toleram módulo não habilitado no console da Open Platform (apps
"seller in-house" precisam marcar as permissões módulo a módulo).
"""

from datetime import date

import psycopg2.extras
from loguru import logger

from utils.db_pool import get_connection
from utils.shopee_core import obter_saude_conta, obter_info_extra_itens
from workers.importar_planilhas import registrar_sincronizacao

FONTE_SAUDE = "API_SAUDE_CONTA"
FONTE_EXTRA = "API_EXTRA_INFO"


def _gravar_metricas_loja(metricas: list[tuple]):
    if not metricas:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, """
                INSERT INTO fato_visao_geral_loja (data_registro, metric_name, metric_value, fonte)
                VALUES %s
                ON CONFLICT (data_registro, metric_name, fonte) DO UPDATE SET
                    metric_value = EXCLUDED.metric_value;
            """, metricas)


def sincronizar_saude_conta():
    """Snapshot diário da saúde da conta. Retorna (dict_para_ui | None, msg).

    Formato validado ao vivo (14/07/2026): metric_list traz metric_name já em
    snake_case ('late_shipment_rate'), current_period e target.value; os
    pontos de penalidade vêm como lista de eventos (somamos latest_point_num).
    """
    saude = obter_saude_conta()
    if saude is None:
        return None, (
            "A API de Account Health não respondeu. Confira o log — se o erro "
            "persistir, acompanhe manualmente em Seller Center → Central da "
            "Conta → Saúde da Conta."
        )

    hoje = date.today()
    metricas = []

    perf = saude.get("performance") or {}
    geral = perf.get("overall_performance") or {}
    if geral.get("rating") is not None:
        # rating oficial: 1=Poor, 2=ImprovementNeeded, 3=Good, 4=Excellent
        metricas.append((hoje, "saude_rating_geral", float(geral["rating"]), FONTE_SAUDE))
    for chave in ("fulfillment_failed", "listing_failed", "custom_service_failed"):
        if geral.get(chave) is not None:
            metricas.append((hoje, f"saude_{chave}", float(geral[chave]), FONTE_SAUDE))

    for m in perf.get("metric_list") or []:
        nome = str(m.get("metric_name", "")).strip().lower().replace(" ", "_")[:90]
        if not nome:
            continue
        if m.get("current_period") is not None:
            metricas.append((hoje, f"saude_{nome}", float(m["current_period"]), FONTE_SAUDE))
        alvo = m.get("target") or {}
        if alvo.get("value") is not None:
            # O comparador importa: response_rate/shop_rating são "quanto MAIOR
            # melhor" (>=) — tratar tudo como teto marcaria falso vermelho.
            sufixo = "_meta_min" if ">" in str(alvo.get("comparator", "<")) else "_meta"
            metricas.append((hoje, f"saude_{nome}{sufixo}", float(alvo["value"]), FONTE_SAUDE))

    eventos_pontos = (saude.get("pontos") or {}).get("penalty_point_list") or []
    total_pontos = sum(int(e.get("latest_point_num", 0) or 0) for e in eventos_pontos)
    metricas.append((hoje, "saude_pontos_penalidade", float(total_pontos), FONTE_SAUDE))
    metricas.append((hoje, "saude_punicoes_ativas",
                     float((saude.get("punicoes_ativas") or {}).get("total_count", 0) or 0), FONTE_SAUDE))
    metricas.append((hoje, "saude_anuncios_com_problema",
                     float((saude.get("listagens_com_problema") or {}).get("total_count", 0) or 0), FONTE_SAUDE))
    metricas.append((hoje, "saude_pedidos_atrasados_agora",
                     float((saude.get("pedidos_atrasados") or {}).get("total_count", 0) or 0), FONTE_SAUDE))

    _gravar_metricas_loja(metricas)
    registrar_sincronizacao("SAUDE_CONTA", hoje, hoje, "SUCESSO", len(metricas))
    logger.info(f"Saúde da conta sincronizada: {len(metricas)} métricas.")
    return saude, f"{len(metricas)} métricas de saúde gravadas."


def sincronizar_metricas_api_produtos():
    """Snapshot diário de views/curtidas/vendas acumuladas por item via API.

    Também atualiza nota_media_estrelas/likes_count na dim_produtos (a API de
    extra info é mais fresca que o get_item_base_info do sync de catálogo).
    Retorna (qtd_itens, msg).
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT item_id FROM dim_produtos WHERE item_id > 0 AND status_shopee = 'NORMAL'")
            ids = [r[0] for r in cur.fetchall()]

    if not ids:
        return 0, "Nenhum produto NORMAL na dimensão — rode o sync de catálogo antes."

    extra = obter_info_extra_itens(ids)
    if not extra:
        return 0, "A API não retornou métricas extras (módulo product habilitado?)."

    hoje = date.today()
    snapshot = []
    for item_id, m in extra.items():
        snapshot.extend([
            (item_id, hoje, "api_views_acumuladas", m["views"], FONTE_EXTRA),
            (item_id, hoje, "api_curtidas_acumuladas", m["likes"], FONTE_EXTRA),
            (item_id, hoje, "api_vendas_acumuladas", m["vendas_acumuladas"], FONTE_EXTRA),
            (item_id, hoje, "api_avaliacoes_acumuladas", m["avaliacoes"], FONTE_EXTRA),
        ])

    with get_connection() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, """
                INSERT INTO fato_metricas_produto_importadas (item_id, data_registro, metric_name, metric_value, fonte)
                VALUES %s
                ON CONFLICT (item_id, data_registro, metric_name, fonte) DO UPDATE SET
                    metric_value = EXCLUDED.metric_value;
            """, snapshot)
            psycopg2.extras.execute_values(cur, """
                UPDATE dim_produtos AS p SET
                    nota_media_estrelas = dados.estrelas,
                    likes_count = dados.likes
                FROM (VALUES %s) AS dados(item_id, estrelas, likes)
                WHERE p.item_id = dados.item_id;
            """, [(i, m["estrelas"], m["likes"]) for i, m in extra.items()])

    registrar_sincronizacao("METRICAS_API_PRODUTOS", hoje, hoje, "SUCESSO", len(extra))
    logger.info(f"Métricas extras via API: {len(extra)} itens.")
    return len(extra), "Sucesso"
