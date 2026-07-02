# Extrai o código do Shopee Open API v2 e o Refresh Token
# python pegar_token.py

import os
import sys
import time
import hmac
import hashlib
import requests
from pathlib import Path
from dotenv import load_dotenv

# Carrega o ambiente (Busca o CHAVES_DADOS.env na mesma pasta)
ROOT_DIR = Path(__file__).resolve().parent
sys.path.append(str(ROOT_DIR))
load_dotenv(ROOT_DIR / "CHAVES_DADOS.env")

# 1. PEGA AS CHAVES DIRETAMENTE DO SEU .env
try:
    PARTNER_ID = int(os.getenv("SHOPEE_PARTNER_ID", 0))
    PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY", "").encode('utf-8')
except ValueError:
    print("❌ ERRO: O SHOPEE_PARTNER_ID no seu CHAVES_DADOS.env deve ser apenas números.")
    sys.exit(1)

# A URL que você colocou no painel da Shopee
REDIRECT_URL = "https://google.com" 

def gerar_link_autorizacao():
    path = "/api/v2/shop/auth_partner"
    timestamp = int(time.time())
    base_string = f"{PARTNER_ID}{path}{timestamp}".encode('utf-8')
    sign = hmac.new(PARTNER_KEY, base_string, hashlib.sha256).hexdigest()
    
    link = f"https://partner.shopeemobile.com{path}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}&redirect={REDIRECT_URL}"
    print("\n🔗 1. CLIQUE NESTE LINK E FAÇA LOGIN NA SUA LOJA SHOPEE:")
    print(link)
    print("\n(Após autorizar, você será redirecionado para o Google. Copie o link inteiro lá de cima da barra do navegador e cole aqui embaixo!)")

if __name__ == "__main__":
    # Verificação de segurança rápida
    if PARTNER_ID == 0 or not PARTNER_KEY:
        print("❌ ERRO: As chaves SHOPEE_PARTNER_ID ou SHOPEE_PARTNER_KEY não foram encontradas no arquivo CHAVES_DADOS.env.")
        print("Por favor, preencha essas duas chaves no .env antes de rodar o script.")
        sys.exit(1)

    gerar_link_autorizacao()
    
    url_google = input("\nCole a URL que o Google abriu aqui: ")
    
    try:
        # Extrai o código e o Shop ID da URL que a Shopee devolveu
        code = url_google.split("code=")[1].split("&")[0]
        shop_id = url_google.split("shop_id=")[1].split("&")[0]
        
        print(f"\n✅ SHOPEE_SHOP_ID encontrado: {shop_id}")
        
        # Pede para a Shopee trocar o 'code' pelo 'refresh_token' definitivo
        path_token = "/api/v2/auth/token/get"
        ts = int(time.time())
        base_token = f"{PARTNER_ID}{path_token}{ts}".encode('utf-8')
        sign_token = hmac.new(PARTNER_KEY, base_token, hashlib.sha256).hexdigest()
        
        payload = {
            "code": code,
            "shop_id": int(shop_id),
            "partner_id": PARTNER_ID
        }
        
        url_api = f"https://partner.shopeemobile.com{path_token}?partner_id={PARTNER_ID}&timestamp={ts}&sign={sign_token}"
        
        res = requests.post(url_api, json=payload).json()
        
        if res.get('error'):
            print(f"\n❌ A Shopee retornou um erro: {res.get('message')}")
        else:
            print(f"✅ SHOPEE_REFRESH_TOKEN encontrado: {res.get('refresh_token')}")
            print("\n🎉 Cole o Shop ID e o Refresh Token no seu arquivo CHAVES_DADOS.env e está tudo pronto!")
        
    except Exception as e:
        print("\n❌ Erro ao extrair o código. Verifique se copiou a URL do Google inteira corretamente.")