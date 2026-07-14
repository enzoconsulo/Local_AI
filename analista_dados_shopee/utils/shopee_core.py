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

        # 🤫 SILENCIADOR DE 404 (Ignora bloqueios de Tráfego e Ads)
        if response.status_code == 404 and ("/api/v2/insight" in path or "/api/v2/ads" in path):
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