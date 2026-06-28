import os
import sys
from datetime import datetime
import psycopg2
from psycopg2.extras import execute_values
from loguru import logger
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

# ATUALIZADO: Apontando para o ficheiro correto
load_dotenv(ROOT_DIR / "CHAVES_DADOS.env")

# ATUALIZADO: Importação direta e segura
from utils.shopee_core import chamar_shopee_api

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
            # ATUALIZADO: pedindo também o motivo de cancelamento
            "response_optional_fields": "buyer_user_id,item_list,cancel_reason"
        }
        response = chamar_shopee_api(path_order_detail, params)
        
        if response and "order_list" in response:
            for order in response["order_list"]:
                # ATUALIZADO: motivo de cancelamento, quando existir.
                # Isso cobre CANCELAMENTOS. Devolução/reembolso pós-entrega na
                # Shopee é outro fluxo (API de Returns, /api/v2/returns/...),
                # que este script ainda não consulta — se quiser o motivo de
                # devolução também, é um sync separado.
                motivo = order.get("cancel_reason") or None
                
                pedidos.append({
                    "order_sn": order["order_sn"],
                    "data_hora_criacao": datetime.fromtimestamp(order["create_time"]).strftime('%Y-%m-%d %H:%M:%S'),
                    "uf_destino": order.get("region", "BR"),
                    "status_pedido": order["order_status"],
                    "motivo_cancelamento_devolucao": motivo
                })
                for item in order.get("item_list", []):
                    itens_pedido.append({
                        "order_sn": order["order_sn"],
                        "model_id": item["model_id"] if item["model_id"] != 0 else item["item_id"], 
                        "quantidade": item["model_quantity_purchased"],
                        "preco_praticado": item["model_discounted_price"]
                    })
    return pedidos, itens_pedido

def obter_dados_repasse(order_sns_concluidos):
    path_escrow = "/api/v2/payment/get_escrow_detail"
    repasses = []
    for order_sn in order_sns_concluidos:
        response = chamar_shopee_api(path_escrow, {"order_sn": order_sn})
        if response and "order_income" in response:
            income = response["order_income"]
            
            # ATUALIZADO: custo de frete reverso. O nome exato do campo varia por
            # região/versão da API da Shopee — tentamos as variações mais comuns.
            # IMPORTANTE: dê um print(income) uma vez com um pedido devolvido real
            # e confirme qual chave aparece de fato; ajuste a lista abaixo se preciso.
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
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"),
            database=os.getenv("POSTGRES_DB"), user=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD")
        )
        cur = conn.cursor()
        
        # ATUALIZADO: grava e atualiza motivo_cancelamento_devolucao
        query_pedidos = """
            INSERT INTO fato_pedidos_venda (order_sn, data_hora_criacao, uf_destino, status_pedido, motivo_cancelamento_devolucao)
            VALUES %s ON CONFLICT (order_sn) DO UPDATE SET 
                status_pedido = EXCLUDED.status_pedido,
                motivo_cancelamento_devolucao = EXCLUDED.motivo_cancelamento_devolucao;
        """
        execute_values(cur, query_pedidos, [tuple(p.values()) for p in pedidos])
        
        order_sns_lote = list(set([i["order_sn"] for i in itens]))
        if order_sns_lote:
            cur.execute("DELETE FROM fato_itens_pedido WHERE order_sn = ANY(%s)", (order_sns_lote,))
            query_itens = "INSERT INTO fato_itens_pedido (order_sn, model_id, quantidade, preco_praticado) VALUES %s;"
            execute_values(cur, query_itens, [tuple(i.values()) for i in itens])

        if repasses:
            # ATUALIZADO: grava e atualiza custo_frete_reverso
            query_repasses = """
                INSERT INTO fato_repasse_escrow (order_sn, comissao_shopee, taxa_servico, taxa_transacao, custo_frete_reverso, lucro_liquido_absoluto)
                VALUES %s ON CONFLICT (order_sn) DO UPDATE SET
                    comissao_shopee = EXCLUDED.comissao_shopee, taxa_servico = EXCLUDED.taxa_servico,
                    taxa_transacao = EXCLUDED.taxa_transacao, custo_frete_reverso = EXCLUDED.custo_frete_reverso,
                    lucro_liquido_absoluto = EXCLUDED.lucro_liquido_absoluto;
            """
            execute_values(cur, query_repasses, [tuple(r.values()) for r in repasses])
            
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Falha crítica ao gravar pedidos: {e}")
        return False

# ==============================================================================
# FUNÇÃO EXPORTADA PARA O STREAMLIT
# ==============================================================================
def sincronizar_pedidos(data_inicio: datetime, data_fim: datetime):
    """Sincroniza pedidos baseado em um range de datas dinâmico."""
    time_from = int(data_inicio.timestamp())
    time_to = int(data_fim.timestamp())
    
    lista_pedidos = obter_pedidos_por_periodo(time_from, time_to)
    if not lista_pedidos:
        return {"status": "sucesso", "registros": 0}
        
    pedidos_detalhados, itens_detalhados = obter_detalhes_pedidos(lista_pedidos)
    
    # Repasses (Escrow) apenas para pedidos finalizados/concluídos
    pedidos_concluidos = [p["order_sn"] for p in pedidos_detalhados if p["status_pedido"] == "COMPLETED"]
    repasses_financeiros = obter_dados_repasse(pedidos_concluidos)
    
    sucesso = salvar_transacoes_no_banco(pedidos_detalhados, itens_detalhados, repasses_financeiros)
    return {"status": "sucesso" if sucesso else "erro", "registros": len(pedidos_detalhados)}