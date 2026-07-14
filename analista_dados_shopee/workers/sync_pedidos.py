import sys
from datetime import datetime
from psycopg2.extras import execute_values
from loguru import logger
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

load_dotenv(ROOT_DIR / "CHAVES_DADOS.env")
from utils.shopee_core import chamar_shopee_api
from utils.db_pool import get_connection


def obter_pedidos_por_periodo(time_from, time_to):
    logger.info(f"Buscando pedidos atualizados entre {datetime.fromtimestamp(time_from).date()} e {datetime.fromtimestamp(time_to).date()}...")
    path_order_list = "/api/v2/order/get_order_list"
    cursor = ""
    order_sns = []

    while True:
        params = {
            "time_range_field": "update_time",
            "time_from": time_from,
            "time_to": time_to,
            "page_size": 50,
            "cursor": cursor
        }
        response = chamar_shopee_api(path_order_list, params)
        if not response or not response.get("order_list"): break

        order_sns.extend([order["order_sn"] for order in response["order_list"]])
        if not response.get("more"): break
        cursor = response.get("next_cursor")

    logger.success(f"{len(order_sns)} pedidos encontrados no período.")
    return order_sns


def obter_detalhes_pedidos(order_sns):
    path_order_detail = "/api/v2/order/get_order_detail"
    pedidos, itens_pedido = [], []
    lotes = [order_sns[i:i + 50] for i in range(0, len(order_sns), 50)]

    for lote in lotes:
        params = {
            "order_sn_list": ",".join(lote),
            "response_optional_fields": "buyer_user_id,item_list,cancel_reason"
        }
        response = chamar_shopee_api(path_order_detail, params)

        if response and "order_list" in response:
            for order in response["order_list"]:
                motivo = order.get("cancel_reason") or None

                pedidos.append({
                    "order_sn": order["order_sn"],
                    "data_hora_criacao": datetime.fromtimestamp(order["create_time"]).strftime('%Y-%m-%d %H:%M:%S'),
                    "uf_destino": order.get("region", "BR"),
                    "status_pedido": order["order_status"],
                    "motivo_cancelamento_devolucao": motivo
                })

                for item in order.get("item_list", []):
                    # .get com defaults: um item malformado da API não pode
                    # derrubar a sincronização do período inteiro.
                    item_id = item.get("item_id")
                    if not item_id:
                        logger.warning(f"Item sem item_id no pedido {order['order_sn']}; linha ignorada.")
                        continue
                    model_id = item.get("model_id") or 0
                    itens_pedido.append({
                        "order_sn": order["order_sn"],
                        "item_id": item_id,  # usado só para criar os fantasmas
                        "model_id": model_id if model_id != 0 else item_id,
                        "quantidade": item.get("model_quantity_purchased", 0),
                        "preco_praticado": item.get("model_discounted_price", 0)
                    })
    return pedidos, itens_pedido


def filtrar_pedidos_sem_escrow(order_sns_concluidos):
    """O escrow de um pedido COMPLETED é imutável: pedidos já gravados em
    fato_repasse_escrow não precisam de nova chamada à API (1 chamada/pedido)."""
    if not order_sns_concluidos:
        return []
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT order_sn FROM fato_repasse_escrow WHERE order_sn = ANY(%s)",
                    (order_sns_concluidos,),
                )
                ja_gravados = {row[0] for row in cur.fetchall()}
        pendentes = [sn for sn in order_sns_concluidos if sn not in ja_gravados]
        if ja_gravados:
            logger.info(f"Escrow: {len(ja_gravados)} pedido(s) já no banco, {len(pendentes)} chamada(s) de API evitada(s)... buscando {len(pendentes)} novo(s).")
        return pendentes
    except Exception as e:
        logger.warning(f"Não foi possível filtrar escrow existente; buscando todos: {e}")
        return order_sns_concluidos


def obter_dados_repasse(order_sns_concluidos):
    path_escrow = "/api/v2/payment/get_escrow_detail"
    repasses = []
    for order_sn in order_sns_concluidos:
        response = chamar_shopee_api(path_escrow, {"order_sn": order_sn})
        if response and "order_income" in response:
            income = response["order_income"]

            custo_frete_reverso = (
                income.get("reverse_shipping_fee")
                or income.get("return_shipping_fee")
                or income.get("seller_return_refund")
                or 0.0
            )

            repasses.append({
                "order_sn": order_sn,
                "comissao_shopee": income.get("commission_fee", 0.0),
                "taxa_servico": income.get("service_fee", 0.0),
                "taxa_transacao": income.get("transaction_fee", 0.0),
                "custo_frete_reverso": custo_frete_reverso,
                "lucro_liquido_absoluto": income.get("escrow_amount", 0.0)
            })
    return repasses


def salvar_transacoes_no_banco(pedidos, itens, repasses):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # 1. PRODUTOS/VARIAÇÕES FANTASMAS EM LOTE
                #    Evita erro de FK para itens excluídos da Shopee sem pagar
                #    2 round-trips de banco por item do pedido.
                produtos_fantasma = list({
                    (i['item_id'],) for i in itens
                })
                variacoes_fantasma = list({
                    (i['model_id'], i['item_id']) for i in itens
                })
                if produtos_fantasma:
                    execute_values(cur, """
                        INSERT INTO dim_produtos (item_id, nome_atual, status_shopee, data_criacao)
                        VALUES %s
                        ON CONFLICT (item_id) DO NOTHING;
                    """, produtos_fantasma,
                    template="(%s, 'Produto Excluído (Histórico)', 'DELETADO', CURRENT_TIMESTAMP)")
                if variacoes_fantasma:
                    execute_values(cur, """
                        INSERT INTO dim_variacoes (model_id, item_id, nome_variacao, preco_venda_atual)
                        VALUES %s
                        ON CONFLICT (model_id) DO NOTHING;
                    """, variacoes_fantasma,
                    template="(%s, %s, 'Variação Excluída', 0)")

                # 2. Grava Pedidos
                query_pedidos = """
                    INSERT INTO fato_pedidos_venda (order_sn, data_hora_criacao, uf_destino, status_pedido, motivo_cancelamento_devolucao)
                    VALUES %s ON CONFLICT (order_sn) DO UPDATE SET
                        status_pedido = EXCLUDED.status_pedido,
                        motivo_cancelamento_devolucao = EXCLUDED.motivo_cancelamento_devolucao;
                """
                valores_pedidos = [
                    (p["order_sn"], p["data_hora_criacao"], p["uf_destino"], p["status_pedido"], p["motivo_cancelamento_devolucao"])
                    for p in pedidos
                ]
                if valores_pedidos:
                    execute_values(cur, query_pedidos, valores_pedidos)

                # 3. Grava Itens do Pedido (replace por pedido: espelha a API)
                order_sns_lote = list({i["order_sn"] for i in itens})
                if order_sns_lote:
                    cur.execute("DELETE FROM fato_itens_pedido WHERE order_sn = ANY(%s)", (order_sns_lote,))
                    query_itens = "INSERT INTO fato_itens_pedido (order_sn, model_id, quantidade, preco_praticado) VALUES %s;"
                    valores_itens = [(i["order_sn"], i["model_id"], i["quantidade"], i["preco_praticado"]) for i in itens]
                    execute_values(cur, query_itens, valores_itens)

                # 4. Grava Repasses (Escrow)
                if repasses:
                    query_repasses = """
                        INSERT INTO fato_repasse_escrow (order_sn, comissao_shopee, taxa_servico, taxa_transacao, custo_frete_reverso, lucro_liquido_absoluto)
                        VALUES %s ON CONFLICT (order_sn) DO UPDATE SET
                            comissao_shopee = EXCLUDED.comissao_shopee, taxa_servico = EXCLUDED.taxa_servico,
                            taxa_transacao = EXCLUDED.taxa_transacao, custo_frete_reverso = EXCLUDED.custo_frete_reverso,
                            lucro_liquido_absoluto = EXCLUDED.lucro_liquido_absoluto;
                    """
                    valores_repasses = [
                        (r["order_sn"], r["comissao_shopee"], r["taxa_servico"], r["taxa_transacao"], r["custo_frete_reverso"], r["lucro_liquido_absoluto"])
                        for r in repasses
                    ]
                    execute_values(cur, query_repasses, valores_repasses)
        return True
    except Exception as e:
        logger.error(f"Falha crítica ao gravar pedidos: {e}")
        return False


# ==============================================================================
# FUNÇÃO EXPORTADA PARA O STREAMLIT
# ==============================================================================
def sincronizar_pedidos(data_inicio: datetime, data_fim: datetime):
    time_from = int(data_inicio.timestamp())
    time_to = int(data_fim.timestamp())

    lista_pedidos = obter_pedidos_por_periodo(time_from, time_to)
    if not lista_pedidos:
        return {"status": "sucesso", "registros": 0}

    pedidos_detalhados, itens_detalhados = obter_detalhes_pedidos(lista_pedidos)

    pedidos_concluidos = [p["order_sn"] for p in pedidos_detalhados if p["status_pedido"] == "COMPLETED"]
    pedidos_escrow_pendente = filtrar_pedidos_sem_escrow(pedidos_concluidos)
    repasses_financeiros = obter_dados_repasse(pedidos_escrow_pendente)

    sucesso = salvar_transacoes_no_banco(pedidos_detalhados, itens_detalhados, repasses_financeiros)
    return {"status": "sucesso" if sucesso else "erro", "registros": len(pedidos_detalhados)}
