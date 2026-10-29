import json
import sys
import unicodedata
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


# A API devolve recipient_address.state às vezes como sigla ("SP"), às vezes
# como nome por extenso ("São Paulo"). order.region NÃO serve: é o PAÍS ("BR").
UFS_VALIDAS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
}
_MAPA_ESTADO_UF = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM",
    "bahia": "BA", "ceara": "CE", "distrito federal": "DF",
    "espirito santo": "ES", "goias": "GO", "maranhao": "MA",
    "mato grosso": "MT", "mato grosso do sul": "MS", "minas gerais": "MG",
    "para": "PA", "paraiba": "PB", "parana": "PR", "pernambuco": "PE",
    "piaui": "PI", "rio de janeiro": "RJ", "rio grande do norte": "RN",
    "rio grande do sul": "RS", "rondonia": "RO", "roraima": "RR",
    "santa catarina": "SC", "sao paulo": "SP", "sergipe": "SE",
    "tocantins": "TO",
}


def _uf_do_pedido(order: dict) -> str | None:
    """Extrai a sigla da UF do endereço do destinatário; None = desconhecida."""
    estado = str((order.get("recipient_address") or {}).get("state") or "").strip()
    if not estado:
        return None
    if len(estado) == 2 and estado.upper() in UFS_VALIDAS:
        return estado.upper()
    chave = unicodedata.normalize("NFKD", estado).encode("ascii", "ignore").decode().lower().strip()
    return _MAPA_ESTADO_UF.get(chave)


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


# Campos extras confirmados ao vivo (18/07/2026) para este app in-house:
# comprador (recompra), pay/ship_by/pickup (tempo de preparo REAL vs prazo —
# o gargalo late-shipment da conta) e frete real pago.
CAMPOS_OPCIONAIS_PEDIDO = (
    "buyer_user_id,buyer_username,item_list,cancel_reason,recipient_address,"
    "pay_time,ship_by_date,pickup_done_time,actual_shipping_fee,package_list"
)


def _ts(valor):
    """Epoch da Shopee → datetime; 0/None = evento ainda não aconteceu."""
    try:
        valor = int(valor or 0)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(valor) if valor > 0 else None


def _pedido_do_detalhe(order: dict) -> dict:
    """Projeção de um pedido da API para o formato do DW (campos pós-venda incl.)."""
    pacotes = order.get("package_list") or []
    transportadora = str((pacotes[0] or {}).get("shipping_carrier") or "")[:80] if pacotes else None
    frete = order.get("actual_shipping_fee")
    return {
        "order_sn": order["order_sn"],
        "data_hora_criacao": datetime.fromtimestamp(order["create_time"]).strftime('%Y-%m-%d %H:%M:%S'),
        # UF real do destinatário (order.region é o PAÍS, sempre 'BR')
        "uf_destino": _uf_do_pedido(order),
        "status_pedido": order["order_status"],
        "motivo_cancelamento_devolucao": order.get("cancel_reason") or None,
        "buyer_user_id": int(order["buyer_user_id"]) if order.get("buyer_user_id") else None,
        "buyer_username": str(order.get("buyer_username") or "")[:80] or None,
        "pay_time": _ts(order.get("pay_time")),
        "ship_by_date": _ts(order.get("ship_by_date")),
        "pickup_done_time": _ts(order.get("pickup_done_time")),
        "frete_real": float(frete) if frete not in (None, "") else None,
        "shipping_carrier": transportadora or None,
    }


def obter_detalhes_pedidos(order_sns):
    path_order_detail = "/api/v2/order/get_order_detail"
    pedidos, itens_pedido = [], []
    lotes = [order_sns[i:i + 50] for i in range(0, len(order_sns), 50)]

    for lote in lotes:
        params = {
            "order_sn_list": ",".join(lote),
            "response_optional_fields": CAMPOS_OPCIONAIS_PEDIDO
        }
        response = chamar_shopee_api(path_order_detail, params)

        if response and "order_list" in response:
            for order in response["order_list"]:
                pedidos.append(_pedido_do_detalhe(order))

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
    """O escrow de um pedido COMPLETED é imutável: pedidos já gravados COM
    detalhamento não precisam de nova chamada à API (1 chamada/pedido). Linhas
    no formato antigo (detalhado_em NULL, anteriores à migração 18) são
    buscadas de novo para ganhar o detalhamento."""
    if not order_sns_concluidos:
        return []
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT order_sn FROM fato_repasse_escrow WHERE order_sn = ANY(%s) AND detalhado_em IS NOT NULL",
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


def _dinheiro(valor) -> float:
    try:
        return round(float(valor or 0), 2)
    except (TypeError, ValueError):
        return 0.0


# Colunas de fato_repasse_escrow na ordem do upsert (migração 18).
COLUNAS_REPASSE = (
    "order_sn", "preco_produtos", "comissao_shopee", "taxa_servico", "taxa_transacao",
    "comissao_afiliado", "cupom_vendedor", "recarga_ads", "seguro_frete",
    "frete_liquido_vendedor", "reembolso_devolucao", "custo_frete_reverso",
    "outros_ajustes", "ajuste_pos_venda", "lucro_liquido_absoluto", "escrow_bruto",
)


def _preco_dos_itens(income: dict) -> float:
    """Valor dos produtos = soma de items[].selling_price (preço da linha).

    Conferido em 14/09/2026 contra os 355 repasses gravados: é o campo que fecha
    a conta em 100% dos pedidos. order_selling_price já vem abatido do item
    devolvido em devolução parcial (o reembolso seria descontado duas vezes) e
    fechava só 332 de 355.
    """
    itens = income.get("items") or []
    if itens:
        return round(sum(_dinheiro(item.get("selling_price")) for item in itens), 2)
    return _dinheiro(income.get("order_original_price") or income.get("order_selling_price"))


def repasse_do_escrow(order_sn: str, income: dict) -> dict:
    """Projeta o order_income do get_escrow_detail no formato do DW.

    Nomes de campo conferidos ao vivo em 14/09/2026. Descontos saem POSITIVOS;
    frete_liquido_vendedor e ajuste_pos_venda mantêm o sinal (negativo = saiu
    dinheiro do vendedor). outros_ajustes é a diferença que fecha a conta, para
    o detalhamento sempre somar exatamente o repasse pago:
        preço + frete − descontos + ajuste_pos_venda − outros_ajustes = repasse
    """
    d = _dinheiro
    preco_produtos = _preco_dos_itens(income)
    frete_liquido = d(income.get("buyer_paid_shipping_fee")) + d(income.get("final_shipping_fee"))
    descontos = {
        "comissao_shopee": d(income.get("commission_fee")),
        "taxa_servico": d(income.get("service_fee")),
        # Taxa de cartão parcelado paga pelo COMPRADOR (buyer_transaction_fee) não sai do vendedor.
        "taxa_transacao": d(income.get("seller_transaction_fee"))
                          + max(0.0, d(income.get("credit_card_transaction_fee")) - d(income.get("buyer_transaction_fee"))),
        "comissao_afiliado": d(income.get("order_ams_commission_fee")),
        "cupom_vendedor": d(income.get("voucher_from_seller")),
        "recarga_ads": d(income.get("ads_escrow_top_up_fee_or_technical_support_fee")),
        "seguro_frete": d(income.get("shipping_seller_protection_fee_amount"))
                        + d(income.get("delivery_seller_protection_fee_premium_amount")),
        # A API devolve reembolso e frete reverso negativos: gravamos o valor que saiu.
        "reembolso_devolucao": abs(d(income.get("seller_return_refund"))),
        "custo_frete_reverso": abs(d(income.get("reverse_shipping_fee")))
                               + abs(d(income.get("final_return_to_seller_shipping_fee"))),
    }
    # Ajuste feito DEPOIS do pagamento: devolução tardia tira dinheiro (negativo),
    # cobertura de devolução põe de volta (positivo). Já está no escrow ajustado.
    ajuste_pos_venda = d(income.get("total_adjustment_amount"))
    ajustado = income.get("escrow_amount_after_adjustment")
    repasse = d(ajustado if ajustado is not None else income.get("escrow_amount"))
    outros = round(preco_produtos + frete_liquido - sum(descontos.values()) + ajuste_pos_venda - repasse, 2)
    return {
        "order_sn": order_sn,
        "preco_produtos": preco_produtos,
        **{k: round(v, 2) for k, v in descontos.items()},
        "frete_liquido_vendedor": round(frete_liquido, 2),
        "outros_ajustes": outros,
        "ajuste_pos_venda": ajuste_pos_venda,
        "lucro_liquido_absoluto": repasse,
        "escrow_bruto": json.dumps(income, ensure_ascii=False),
    }


def obter_dados_repasse(order_sns_concluidos):
    path_escrow = "/api/v2/payment/get_escrow_detail"
    repasses = []
    for order_sn in order_sns_concluidos:
        response = chamar_shopee_api(path_escrow, {"order_sn": order_sn})
        if response and "order_income" in response:
            repasses.append(repasse_do_escrow(order_sn, response["order_income"]))
    return repasses


def _gravar_repasses(cur, repasses):
    """Upsert do repasse detalhado; detalhado_em marca a linha como formato novo."""
    if not repasses:
        return
    colunas = ", ".join(COLUNAS_REPASSE)
    atualizar = ", ".join(f"{c} = EXCLUDED.{c}" for c in COLUNAS_REPASSE if c != "order_sn")
    execute_values(
        cur,
        f"""
        INSERT INTO fato_repasse_escrow ({colunas}, detalhado_em)
        VALUES %s ON CONFLICT (order_sn) DO UPDATE SET {atualizar}, detalhado_em = EXCLUDED.detalhado_em;
        """,
        [tuple(r[c] for c in COLUNAS_REPASSE) + (datetime.now(),) for r in repasses],
    )


def reprocessar_repasses_gravados() -> int:
    """Recalcula o detalhamento a partir do escrow_bruto já gravado, sem chamar a
    API. Use quando a regra de repasse_do_escrow mudar."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT order_sn, escrow_bruto FROM fato_repasse_escrow WHERE escrow_bruto IS NOT NULL")
            repasses = [
                repasse_do_escrow(sn, bruto if isinstance(bruto, dict) else json.loads(bruto))
                for sn, bruto in cur.fetchall()
            ]
            _gravar_repasses(cur, repasses)
    return len(repasses)


def detalhar_repasses_pendentes(limite: int | None = None) -> dict:
    """Busca de novo, na API, o repasse dos pedidos gravados antes do detalhamento
    (migração 18). Pedidos antigos não voltam na janela do sync por update_time,
    então sem isto ficariam para sempre sem detalhe. 1 chamada por pedido."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT order_sn FROM fato_repasse_escrow WHERE detalhado_em IS NULL ORDER BY order_sn"
                + (" LIMIT %s" if limite else ""),
                (limite,) if limite else None,
            )
            pendentes = [linha[0] for linha in cur.fetchall()]
    if not pendentes:
        return {"pendentes": 0, "detalhados": 0}

    logger.info(f"Detalhando o repasse de {len(pendentes)} pedido(s) antigo(s) pela API...")
    detalhados = 0
    # Grava a cada lote: se o processo cair no meio, a próxima execução
    # continua de onde parou (só busca o que ainda está com detalhado_em NULL).
    for inicio in range(0, len(pendentes), 20):
        repasses = obter_dados_repasse(pendentes[inicio:inicio + 20])
        with get_connection() as conn:
            with conn.cursor() as cur:
                _gravar_repasses(cur, repasses)
        detalhados += len(repasses)
        logger.info(f"Repasses detalhados: {detalhados}/{len(pendentes)}")
    logger.success(f"{detalhados} de {len(pendentes)} repasse(s) detalhado(s).")
    return {"pendentes": len(pendentes), "detalhados": detalhados}


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

                # 2. Grava Pedidos (COALESCE nos campos pós-venda: a API pode
                #    omitir um campo num refresh e não pode apagar o que já
                #    foi capturado; delivered/logistics são do worker de rastreio)
                query_pedidos = """
                    INSERT INTO fato_pedidos_venda (
                        order_sn, data_hora_criacao, uf_destino, status_pedido,
                        motivo_cancelamento_devolucao, buyer_user_id, buyer_username,
                        pay_time, ship_by_date, pickup_done_time, frete_real, shipping_carrier
                    )
                    VALUES %s ON CONFLICT (order_sn) DO UPDATE SET
                        status_pedido = EXCLUDED.status_pedido,
                        motivo_cancelamento_devolucao = EXCLUDED.motivo_cancelamento_devolucao,
                        uf_destino = COALESCE(EXCLUDED.uf_destino, fato_pedidos_venda.uf_destino),
                        buyer_user_id = COALESCE(EXCLUDED.buyer_user_id, fato_pedidos_venda.buyer_user_id),
                        buyer_username = COALESCE(EXCLUDED.buyer_username, fato_pedidos_venda.buyer_username),
                        pay_time = COALESCE(EXCLUDED.pay_time, fato_pedidos_venda.pay_time),
                        ship_by_date = COALESCE(EXCLUDED.ship_by_date, fato_pedidos_venda.ship_by_date),
                        pickup_done_time = COALESCE(EXCLUDED.pickup_done_time, fato_pedidos_venda.pickup_done_time),
                        frete_real = COALESCE(EXCLUDED.frete_real, fato_pedidos_venda.frete_real),
                        shipping_carrier = COALESCE(EXCLUDED.shipping_carrier, fato_pedidos_venda.shipping_carrier);
                """
                valores_pedidos = [
                    (p["order_sn"], p["data_hora_criacao"], p["uf_destino"], p["status_pedido"],
                     p["motivo_cancelamento_devolucao"], p.get("buyer_user_id"), p.get("buyer_username"),
                     p.get("pay_time"), p.get("ship_by_date"), p.get("pickup_done_time"),
                     p.get("frete_real"), p.get("shipping_carrier"))
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

                # 4. Grava Repasses (Escrow) com o detalhamento completo
                _gravar_repasses(cur, repasses)
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


if __name__ == "__main__":
    # python workers/sync_pedidos.py --detalhar-repasses     (busca na API o detalhe que falta)
    # python workers/sync_pedidos.py --reprocessar-repasses  (recalcula do escrow_bruto, sem API)
    if "--detalhar-repasses" in sys.argv:
        print(detalhar_repasses_pendentes())
    if "--reprocessar-repasses" in sys.argv:
        print(f"{reprocessar_repasses_gravados()} repasse(s) recalculado(s).")
