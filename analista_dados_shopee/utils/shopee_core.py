import os
import time
import hmac
import hashlib
import requests
from dotenv import load_dotenv
from loguru import logger
from pathlib import Path

# Carrega chaves da raiz (Atualizado para a arquitetura de Dados)
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / "CHAVES_DADOS.env")

PARTNER_ID = int(os.getenv("SHOPEE_PARTNER_ID", 0))
PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY", "").encode('utf-8')
SHOP_ID = int(os.getenv("SHOPEE_SHOP_ID", 0))
ACCESS_TOKEN = os.getenv("SHOPEE_REFRESH_TOKEN", "")
BASE_URL = "https://partner.shopeemobile.com"

def gerar_assinatura(path):
    """Gera a assinatura criptografada obrigatória da Shopee v2."""
    timestamp = int(time.time())
    base_string = f"{PARTNER_ID}{path}{timestamp}{ACCESS_TOKEN}{SHOP_ID}".encode('utf-8')
    sign = hmac.new(PARTNER_KEY, base_string, hashlib.sha256).hexdigest()
    return timestamp, sign

def chamar_shopee_api(path, params=None, method="GET", payload=None):
    """
    Motor centralizado de chamadas para a Shopee API v2.
    Suporta GET (leitura de catálogo/pedidos) e POST (atuação da IA).
    """
    if params is None: params = {}
    timestamp, sign = gerar_assinatura(path)
    
    # Parâmetros de URL obrigatórios para autenticação em TODOS os endpoints
    params.update({
        "partner_id": PARTNER_ID,
        "timestamp": timestamp,
        "access_token": ACCESS_TOKEN,
        "shop_id": SHOP_ID,
        "sign": sign
    })
    
    url = f"{BASE_URL}{path}"
    
    try:
        if method.upper() == "GET":
            response = requests.get(url, params=params, timeout=30)
        elif method.upper() == "POST":
            # No POST, a Shopee exige as credenciais na URL (params) e os dados no body (json)
            response = requests.post(url, params=params, json=payload, timeout=30)
        else:
            logger.error(f"Método HTTP não suportado: {method}")
            return None

        response.raise_for_status()
        data = response.json()
        
        # A Shopee pode retornar HTTP 200, mas conter o erro no payload
        if data.get("error"):
            logger.error(f"Shopee API Erro ({path}): {data.get('error')} - {data.get('message')}")
            return None
            
        return data.get("response", {})
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Falha de Rede ao tentar {method} em {path}: {e}")
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
    """
    Cria uma campanha de Desconto Flash (Etiqueta Amarela) e notifica os clientes.
    """
    path_add_discount = "/api/v2/discount/add_discount"
    path_add_item = "/api/v2/discount/add_discount_item"
    
    # 1. Configurar a cronologia (Começa daqui a 30 minutos e dura X horas)
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
    
    # 2. Injetar o produto dentro desta campanha
    payload_item = {
        "discount_id": discount_id,
        "item_list": [
            {
                "item_id": item_id,
                "model_list": [
                    {
                        "model_id": model_id,
                        "model_promotion_price": float(preco_promocional),
                        "model_promotion_stock": 0 # Na Shopee, 0 = Sem limite (Usa o estoque normal)
                    }
                ]
            }
        ]
    }
    
    resp_item = chamar_shopee_api(path_add_item, method="POST", payload=payload_item)
    
    if resp_item is not None and not resp_item.get("error"):
        return True, f"Etiqueta de Promoção gerada! Ficará ativa e visível na loja em ~30 minutos."
        
    return False, f"Falha ao vincular o produto à campanha: {resp_item}"

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