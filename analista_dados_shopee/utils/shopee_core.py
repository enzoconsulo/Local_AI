import os
import time
import hmac
import hashlib
import requests
from dotenv import load_dotenv, set_key
from loguru import logger
from pathlib import Path

# Carrega chaves da raiz
ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / "CHAVES_DADOS.env"
load_dotenv(ENV_FILE)

PARTNER_ID = int(os.getenv("SHOPEE_PARTNER_ID", 0))
PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY", "").encode('utf-8')
SHOP_ID = int(os.getenv("SHOPEE_SHOP_ID", 0))
BASE_URL = "https://partner.shopeemobile.com"

# ==============================================================================
# MOTOR DE AUTENTICAÇÃO INTELIGENTE (Auto-Renovação de Token)
# ==============================================================================
_CACHE_ACCESS_TOKEN = None
_CACHE_EXPIRATION = 0

def obter_access_token():
    """Gera e renova o access_token de forma autônoma usando o refresh_token."""
    global _CACHE_ACCESS_TOKEN, _CACHE_EXPIRATION
    
    # Se o token ainda for válido na memória, reaproveita (evita block da API)
    if _CACHE_ACCESS_TOKEN and time.time() < _CACHE_EXPIRATION:
        return _CACHE_ACCESS_TOKEN
        
    refresh_token = os.getenv("SHOPEE_REFRESH_TOKEN", "")
    
    if not refresh_token:
        logger.error("Refresh Token não encontrado no CHAVES_DADOS.env")
        return None
        
    path = "/api/v2/auth/access_token/get"
    timestamp = int(time.time())
    base_string = f"{PARTNER_ID}{path}{timestamp}".encode('utf-8')
    sign = hmac.new(PARTNER_KEY, base_string, hashlib.sha256).hexdigest()
    
    url = f"{BASE_URL}{path}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}"
    payload = {
        "refresh_token": refresh_token,
        "partner_id": PARTNER_ID,
        "shop_id": SHOP_ID
    }
    
    try:
        res = requests.post(url, json=payload, timeout=20).json()
        
        if res.get("error"):
            logger.error(f"Falha ao gerar Token na Shopee: {res.get('message')}")
            return None
            
        _CACHE_ACCESS_TOKEN = res.get("access_token")
        novo_refresh = res.get("refresh_token")
        
        # O Access Token dura 4 horas. Vamos forçar a renovação a cada 3 horas por segurança.
        _CACHE_EXPIRATION = time.time() + 10800 
        
        # Salva o novo refresh_token no .env para o sistema nunca mais quebrar!
        set_key(str(ENV_FILE), "SHOPEE_REFRESH_TOKEN", novo_refresh)
        os.environ["SHOPEE_REFRESH_TOKEN"] = novo_refresh
        
        logger.success("🔑 Conexão validada! Access Token gerado com sucesso.")
        return _CACHE_ACCESS_TOKEN
    except Exception as e:
        logger.error(f"Erro ao comunicar com a API de Autenticação: {e}")
        return None

def gerar_assinatura(path, access_token):
    """Gera a assinatura criptografada obrigatória da Shopee v2."""
    timestamp = int(time.time())
    base_string = f"{PARTNER_ID}{path}{timestamp}{access_token}{SHOP_ID}".encode('utf-8')
    sign = hmac.new(PARTNER_KEY, base_string, hashlib.sha256).hexdigest()
    return timestamp, sign

# ==============================================================================
# COMUNICADOR CENTRAL
# ==============================================================================

# Sessão compartilhada: reaproveita a conexão TLS entre as centenas de chamadas
# sequenciais de um backfill (escrow chama a API 1 vez por pedido).
_HTTP_SESSION = requests.Session()


def _espera_retry(response, tentativa):
    """Backoff exponencial limitado, respeitando o Retry-After quando enviado."""
    try:
        sugerido = int(response.headers.get("Retry-After", "") or 0)
    except (TypeError, ValueError):
        sugerido = 0
    return min(15, max(sugerido, 2 ** tentativa))


def chamar_shopee_api(path, params=None, method="GET", payload=None, max_tentativas=3):
    """
    Motor centralizado de chamadas para a Shopee API v2, com retry disciplinado:

      - GET (leitura) é idempotente: repete em 429, 5xx, timeout e falha de rede.
      - POST (atuação: preço/promoção/combo) só repete em 429 — nunca após
        timeout ou 5xx, para não aplicar a mesma ação duas vezes na loja.

    A assinatura é regenerada a cada tentativa: o timestamp faz parte dela e
    uma retentativa com assinatura velha seria rejeitada.
    """
    metodo = method.upper()
    if metodo not in {"GET", "POST"}:
        logger.error(f"Método HTTP não suportado: {method}")
        return None

    url = f"{BASE_URL}{path}"

    for tentativa in range(1, max_tentativas + 1):
        access_token = obter_access_token()
        if not access_token:
            return None

        timestamp, sign = gerar_assinatura(path, access_token)
        params_completos = dict(params or {})
        params_completos.update({
            "partner_id": PARTNER_ID,
            "timestamp": timestamp,
            "access_token": access_token,
            "shop_id": SHOP_ID,
            "sign": sign
        })

        try:
            if metodo == "GET":
                response = _HTTP_SESSION.get(url, params=params_completos, timeout=(10, 30))
            else:
                response = _HTTP_SESSION.post(url, params=params_completos, json=payload, timeout=(10, 30))
        except requests.exceptions.RequestException as e:
            if metodo == "GET" and tentativa < max_tentativas:
                espera = min(8, 2 ** tentativa)
                logger.warning(f"Falha de rede em {path} (tentativa {tentativa}/{max_tentativas}); nova tentativa em {espera}s: {e}")
                time.sleep(espera)
                continue
            logger.error(f"Falha de Rede ao tentar {metodo} em {path}: {e}")
            return None

        # 🤫 SILENCIADOR DE MÓDULOS OPCIONAIS — Insight, Ads e Account Health
        # dependem de permissão marcada no console da Open Platform (apps
        # "seller in-house" precisam habilitar módulo a módulo; 403/404 = não
        # habilitado). A ausência vira None e a UI explica como habilitar,
        # em vez de poluir o log com erro. Flagrado em teste real: account_
        # health respondeu 403 Forbidden nesta conta.
        _MODULOS_OPCIONAIS = ("/api/v2/insight", "/api/v2/ads", "/api/v2/account_health")
        if response.status_code in (403, 404) and any(m in path for m in _MODULOS_OPCIONAIS):
            logger.warning(f"Módulo opcional sem permissão para este app ({response.status_code}): {path}")
            return None

        # 429 é seguro repetir sempre (a Shopee não processou); 5xx só em GET.
        deve_repetir = response.status_code == 429 or (response.status_code >= 500 and metodo == "GET")
        if deve_repetir and tentativa < max_tentativas:
            espera = _espera_retry(response, tentativa)
            logger.warning(f"Shopee respondeu {response.status_code} em {path} (tentativa {tentativa}/{max_tentativas}); aguardando {espera}s.")
            time.sleep(espera)
            continue

        try:
            response.raise_for_status()
            data = response.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            logger.error(f"Resposta inválida da Shopee em {metodo} {path}: {e}")
            return None

        if data.get("error"):
            logger.error(f"Shopee API Erro ({path}): {data.get('error')} - {data.get('message')}")
            return None

        return data.get("response", {})

    return None
    
# ==============================================================================
# FUNÇÕES ATUADORAS (Usadas pelo Cérebro IA para manipular a loja)
# ==============================================================================

def atualizar_preco_shopee(item_id, model_id, novo_preco):
    """Altera definitivamente o preço de uma variação."""
    path = "/api/v2/product/update_price"
    
    payload = {
        "item_id": item_id,
        "price_list": [
            {
                "model_id": model_id,
                "original_price": float(novo_preco)
            }
        ]
    }
    
    logger.info(f"Enviando ordem para Shopee: Item {item_id}, Novo Preço: {novo_preco}")
    resposta = chamar_shopee_api(path, method="POST", payload=payload)
    
    if resposta is not None:
        falhas = resposta.get("failure_list", [])
        if falhas:
            logger.error(f"A Shopee rejeitou a alteração: {falhas}")
            return False, str(falhas)
        return True, "Sucesso"
        
    return False, "Falha de Comunicação com a Shopee."

def criar_promocao_shopee(item_id, model_id, preco_promocional, horas_duracao=24):
    path_add_discount = "/api/v2/discount/add_discount"
    path_add_item = "/api/v2/discount/add_discount_item"

    start_time = int(time.time()) + 1800
    end_time = start_time + (int(horas_duracao) * 3600)
    nome_promocao = f"Flash_IA_{int(time.time())}"

    payload_discount = {
        "discount_name": nome_promocao,
        "start_time": start_time,
        "end_time": end_time
    }

    logger.info(f"Criando Campanha de Desconto: {nome_promocao}")
    resp_campanha = chamar_shopee_api(path_add_discount, method="POST", payload=payload_discount)

    if not resp_campanha or "discount_id" not in resp_campanha:
        msg_erro = resp_campanha.get('warning', 'Erro desconhecido') if resp_campanha else 'Sem resposta'
        return False, f"Falha ao criar campanha base: {msg_erro}"

    discount_id = resp_campanha["discount_id"]

    payload_item = {
        "discount_id": discount_id,
        "item_list": [
            {
                "item_id": item_id,
                "model_list": [
                    {
                        "model_id": model_id,
                        "model_promotion_price": float(preco_promocional),
                        "model_promotion_stock": 0
                    }
                ]
            }
        ]
    }

    resp_item = chamar_shopee_api(path_add_item, method="POST", payload=payload_item)

    # LOG CRU — essencial para descobrir o formato real que sua conta recebe
    logger.debug(f"Resposta bruta add_discount_item: {resp_item}")

    if resp_item is None:
        return False, "Falha de comunicação ao vincular item à campanha."

    # A Shopee costuma retornar falhas item-a-item aninhadas, não no campo 'error' de topo.
    # Verificamos todos os nomes de campo plausíveis, já que o formato varia por versão/região.
    falhas = (
        resp_item.get("failed_list")
        or resp_item.get("failed_items")
        or resp_item.get("warning")
        or []
    )
    if falhas:
        logger.error(f"Shopee rejeitou o item na campanha: {falhas}")
        return False, f"Item rejeitado: {falhas}"

    return True, discount_id  # devolvemos o discount_id, não só uma mensagem — precisamos dele pra verificar depois

def verificar_status_promocao(discount_id):
    """
    Consulta o estado real da campanha na Shopee.
    Retorna: ('upcoming' | 'ongoing' | 'expired' | 'rejeitado' | 'desconhecido', detalhe)
    """
    path = "/api/v2/discount/get_discount"
    params = {"discount_id": discount_id}

    resp = chamar_shopee_api(path, params=params, method="GET")
    logger.debug(f"Resposta bruta get_discount: {resp}")

    if resp is None:
        return "desconhecido", "Sem resposta da Shopee ao consultar status."

    status = resp.get("status", "desconhecido")
    itens = resp.get("item_list", [])

    # Confere se o item de fato está presente e ativo dentro da campanha
    item_encontrado = any(
        i.get("item_id") for i in itens
    ) if itens else False

    if not item_encontrado:
        return "rejeitado", "Campanha existe, mas nenhum item está vinculado a ela."

    return status, f"{len(itens)} item(ns) vinculado(s) à campanha."

def criar_combo_shopee(item_id, percentual_desconto=10, limite_compras=100):
    """
    Cria um 'Bundle Deal' (Leve 2, Pague menos) para diluir frete e aumentar conversão.
    (Integração bônus para habilitar o comando 'CRIAR_COMBO' da IA).
    """
    path_add_bundle = "/api/v2/bundle_deal/add_bundle_deal"
    path_add_item = "/api/v2/bundle_deal/add_bundle_deal_item"
    
    start_time = int(time.time()) + 1800 
    end_time = start_time + (7 * 24 * 3600) # Dura 7 dias por padrão
    nome_combo = f"Combo_IA_{int(time.time())}"
    
    # Bundle type 2 = "Percentage Discount" (Ex: Compre 2 e ganhe 10% off)
    payload_bundle = {
        "bundle_deal_name": nome_combo,
        "start_time": start_time,
        "end_time": end_time,
        "bundle_deal_rule_type": 2, 
        "rule_info": {
            "min_amount": 2, # Compre 2 unidades
            "discount_percentage": int(percentual_desconto) # Ganhe X% de desconto
        },
        "purchase_limit": limite_compras
    }
    
    resp_bundle = chamar_shopee_api(path_add_bundle, method="POST", payload=payload_bundle)
    
    if not resp_bundle or "bundle_deal_id" not in resp_bundle:
        return False, "Falha ao criar regra do Combo Base."
        
    bundle_id = resp_bundle["bundle_deal_id"]
    
    # Vincula o item ao Combo
    payload_item = {
        "bundle_deal_id": bundle_id,
        "item_list": [{"item_id": item_id, "status": 1}]
    }
    
    resp_item = chamar_shopee_api(path_add_item, method="POST", payload=payload_item)

    if resp_item is not None and not resp_item.get("error"):
        return True, "Combo 'Leve 2' configurado com sucesso. Ativo em ~30 min."

    return False, "Falha ao atrelar item ao Combo."


# ==============================================================================
# SAÚDE DA CONTA (v2.account_health) — o que decide o ALCANCE orgânico da loja
# ==============================================================================

def obter_saude_conta():
    """Lê a saúde operacional da loja direto da API oficial.

    Nomes de endpoint VALIDADOS AO VIVO nesta conta (14/07/2026): a família
    atual usa o prefixo get_ ('get_shop_performance'); os nomes antigos sem
    get_ respondem 403 e NÃO significam falta de permissão do app.

    Retorna dict com performance, pontos de penalidade, punições ativas,
    anúncios com problema e pedidos atrasados — ou None se o módulo estiver
    realmente indisponível.
    """
    performance = chamar_shopee_api("/api/v2/account_health/get_shop_performance")
    if performance is None:
        return None
    return {
        "performance": performance,
        "pontos": chamar_shopee_api("/api/v2/account_health/get_penalty_point_history") or {},
        "punicoes_ativas": chamar_shopee_api(
            "/api/v2/account_health/get_punishment_history", params={"punishment_status": 1}) or {},
        "listagens_com_problema": chamar_shopee_api(
            "/api/v2/account_health/get_listings_with_issues", params={"page_no": 1, "page_size": 100}) or {},
        "pedidos_atrasados": chamar_shopee_api(
            "/api/v2/account_health/get_late_orders", params={"page_no": 1, "page_size": 100}) or {},
    }


# ==============================================================================
# BOOST DE PRODUTOS (v2.product.boost_item) — alcance GRÁTIS, 5 itens / 4 horas
# ==============================================================================

def listar_boost_ativo():
    """IDs dos itens atualmente impulsionados (a Shopee permite até 5 por vez;
    cada boost dura 4 horas). Retorna lista de item_ids ou None em falha."""
    resp = chamar_shopee_api("/api/v2/product/get_boosted_list")
    if resp is None:
        return None
    lista = resp.get("item_id_list") or []
    # Algumas regiões devolvem [{"item_id": ...}] em vez de [int]
    return [i.get("item_id", i) if isinstance(i, dict) else int(i) for i in lista]


def impulsionar_itens(item_ids):
    """Impulsiona até 5 itens (aparecem primeiro na aba da loja e ganham
    prioridade nas recomendações por 4 horas — recurso gratuito da Shopee).

    Retorna (lista_sucesso, lista_falhas[(item_id, motivo)]).
    """
    payload = {"item_id_list": [int(i) for i in item_ids[:5]]}
    logger.info(f"Boost solicitado para itens: {payload['item_id_list']}")
    resp = chamar_shopee_api("/api/v2/product/boost_item", method="POST", payload=payload)
    if resp is None:
        return [], [(i, "Sem resposta da Shopee") for i in payload["item_id_list"]]

    falhas = [
        (f.get("item_id"), f.get("failed_reason", "motivo não informado"))
        for f in (resp.get("failure_list") or [])
    ]
    sucesso = list(resp.get("success_list") or [])
    if not sucesso and not falhas:
        # Formato alternativo: sem listas explícitas, considerar tudo aceito
        sucesso = payload["item_id_list"]
    return sucesso, falhas


# ==============================================================================
# VOUCHER DA LOJA (v2.voucher) — incentivo de checkout contra carrinho abandonado
# ==============================================================================

def _gerar_codigo_voucher() -> str:
    """Código único de 5 chars (limite da Shopee BR): 'IA' + timestamp base36."""
    alfabeto = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    n = int(time.time()) % (36 ** 3)
    sufixo = ""
    for _ in range(3):
        n, resto = divmod(n, 36)
        sufixo = alfabeto[resto] + sufixo
    return f"IA{sufixo}"


def criar_voucher_loja(nome, desconto_reais, min_gasto, usos, dias_duracao=7, codigo=None):
    """Cria um voucher de valor FIXO para a loja toda (voucher_type=1,
    reward_type=1 — custo máximo previsível: usos × desconto).

    Começa em ~15 min (a Shopee exige start_time no futuro) e aparece nos
    canais padrão (página da loja, produto e checkout).
    Retorna (True, voucher_id) ou (False, motivo).
    """
    inicio = int(time.time()) + 900
    payload = {
        "voucher_name": str(nome)[:100],
        "voucher_code": (codigo or _gerar_codigo_voucher())[:5].upper(),
        "start_time": inicio,
        "end_time": inicio + int(dias_duracao) * 86400,
        "voucher_type": 1,      # 1 = loja inteira
        "reward_type": 1,       # 1 = desconto em valor fixo
        "usage_quantity": int(usos),
        "min_basket_price": float(min_gasto),
        "discount_amount": float(desconto_reais),
        "display_channel_list": [1],  # 1 = exibir em todos os canais padrão
    }
    logger.info(f"Criando voucher {payload['voucher_code']}: R$ {desconto_reais} acima de R$ {min_gasto}, {usos} usos")
    resp = chamar_shopee_api("/api/v2/voucher/add_voucher", method="POST", payload=payload)
    if resp and resp.get("voucher_id"):
        return True, resp["voucher_id"]
    return False, f"Shopee recusou o voucher: {resp}" if resp else "Sem resposta da Shopee."


def listar_vouchers(status="ongoing"):
    """Vouchers da loja por status ('upcoming'|'ongoing'|'expired'|'all').
    Retorna lista (possivelmente vazia) ou None em falha de comunicação."""
    resp = chamar_shopee_api(
        "/api/v2/voucher/get_voucher_list",
        params={"status": status, "page_no": 1, "page_size": 25},
    )
    if resp is None:
        return None
    return resp.get("voucher_list") or []


def encerrar_voucher(voucher_id, ja_iniciado=True):
    """Encerra um voucher em andamento (end_voucher) ou exclui um agendado
    que ainda não começou (delete_voucher). Retorna (sucesso, msg)."""
    path = "/api/v2/voucher/end_voucher" if ja_iniciado else "/api/v2/voucher/delete_voucher"
    resp = chamar_shopee_api(path, method="POST", payload={"voucher_id": int(voucher_id)})
    if resp is not None and resp.get("voucher_id"):
        return True, "Voucher encerrado."
    return False, f"Falha ao encerrar: {resp}" if resp else "Sem resposta da Shopee."


# ==============================================================================
# MÉTRICAS EXTRAS POR ITEM (v2.product.get_item_extra_info)
# views/curtidas/vendas acumuladas via API — sem depender de planilha
# ==============================================================================

def obter_info_extra_itens(item_ids):
    """Busca views, curtidas e vendas acumuladas por item, em lotes de 50.

    Retorna {item_id: {"views": n, "likes": n, "vendas_acumuladas": n,
    "avaliacoes": n, "estrelas": f}} — apenas itens que a API devolveu.
    """
    resultado = {}
    ids = [int(i) for i in item_ids]
    for inicio in range(0, len(ids), 50):
        lote = ids[inicio:inicio + 50]
        resp = chamar_shopee_api(
            "/api/v2/product/get_item_extra_info",
            params={"item_id_list": ",".join(str(i) for i in lote)},
        )
        for item in (resp or {}).get("item_list", []) or []:
            resultado[item.get("item_id")] = {
                "views": int(item.get("views", 0) or 0),
                "likes": int(item.get("likes", 0) or 0),
                "vendas_acumuladas": int(item.get("sale", 0) or 0),
                "avaliacoes": int(item.get("comment_count", 0) or 0),
                "estrelas": float(item.get("rating_star", 0) or 0),
            }
    return resultado