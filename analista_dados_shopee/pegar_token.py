# Autoriza a loja na Shopee Open API v2 e grava SHOPEE_SHOP_ID e
# SHOPEE_REFRESH_TOKEN direto no CHAVES_DADOS.env.
#   python pegar_token.py
#
# O login do dono da loja no navegador é o único passo que a Shopee não deixa
# automatizar (é o consentimento do OAuth). Depois dele, a renovação é
# automática: utils/shopee_core.py renova a cada uso e manter_token.py (tarefa
# diária registrada pelo run_local.ps1) renova mesmo com o app fechado, para o
# refresh_token de 30 dias não vencer parado.

import hashlib
import hmac
import os
import re
import sys
import time
import webbrowser
from pathlib import Path

import requests
from dotenv import set_key

ROOT_DIR = Path(__file__).resolve().parent
sys.path.append(str(ROOT_DIR))

import utils.shopee_core as shopee_core
from utils import tunel_shopee

# Precisa bater com a URL de redirect cadastrada no app da Open Platform
REDIRECT_URL = "https://google.com"


def _assinar(path):
    timestamp = int(time.time())
    base = f"{shopee_core.PARTNER_ID}{path}{timestamp}".encode("utf-8")
    return timestamp, hmac.new(shopee_core.PARTNER_KEY, base, hashlib.sha256).hexdigest()


def main():
    if shopee_core.TOKEN_VIA_PI:
        print(f"❌ O token desta loja é do BTT Pi (TOKEN_VIA_PI={shopee_core.TOKEN_VIA_PI}).")
        print("   Autorizar por aqui criaria uma segunda cadeia de token e pode derrubar a do Pi.")
        print("   Se a autorização morreu, rode no Pi: bash ~/shopee-rodizio/scripts/atalhos/gerar_token.sh")
        return 1

    partner_id = shopee_core.PARTNER_ID
    if not partner_id or not shopee_core.PARTNER_KEY:
        print("❌ Preencha SHOPEE_PARTNER_ID e SHOPEE_PARTNER_KEY no CHAVES_DADOS.env antes de rodar.")
        return 1

    # A troca do código também passa pela IP Whitelist: precisa sair pelo IP fixo.
    if not tunel_shopee.garantir_tunel():
        print("❌ O túnel de IP fixo não subiu (veja a mensagem acima e tunel_shopee.log).")
        return 1

    path = "/api/v2/shop/auth_partner"
    timestamp, sign = _assinar(path)
    link = f"{shopee_core.BASE_URL}{path}?partner_id={partner_id}&timestamp={timestamp}&sign={sign}&redirect={REDIRECT_URL}"
    print("\n🔗 1. Abrindo o link de autorização no navegador (se não abrir, copie daqui):")
    print(link)
    print("\n   Faça login com a conta VENDEDORA da loja e clique em Autorizar.")
    webbrowser.open(link)
    print("\n📋 2. Você vai cair no Google com '?code=...&shop_id=...' na barra de endereço.")
    print("   Copie o endereço inteiro e cole aqui (o code vale ~10 minutos e só uma vez).")
    url_colada = input("\nURL: ").strip()

    code = re.search(r"[?&]code=([^&#\s]+)", url_colada)
    shop = re.search(r"[?&]shop_id=(\d+)", url_colada)
    if not code or not shop:
        print("\n❌ Não achei 'code' e 'shop_id' nessa URL. Copie a barra de endereço inteira e rode de novo.")
        return 1
    shop_id = int(shop.group(1))

    path_token = "/api/v2/auth/token/get"
    timestamp, sign = _assinar(path_token)
    try:
        res = requests.post(
            f"{shopee_core.BASE_URL}{path_token}",
            params={"partner_id": partner_id, "timestamp": timestamp, "sign": sign},
            json={"code": code.group(1), "shop_id": shop_id, "partner_id": partner_id},
            timeout=30,
            proxies=shopee_core.PROXIES_SHOPEE,
        ).json()
    except (requests.exceptions.RequestException, ValueError) as exc:
        print(f"\n❌ Falha ao falar com a Shopee: {exc}")
        return 1

    if res.get("error"):
        print(f"\n❌ A Shopee recusou: {res.get('error')} - {res.get('message')}")
        print("   Se o code expirou ou já foi usado, é só rodar o script de novo.")
        return 1

    # Mesmo lock da renovação automática: o app aberto não pode gravar por cima.
    with shopee_core._trava_renovacao_entre_processos():
        set_key(str(shopee_core.ENV_FILE), "SHOPEE_SHOP_ID", str(shop_id))
        set_key(str(shopee_core.ENV_FILE), "SHOPEE_REFRESH_TOKEN", res["refresh_token"])
        os.environ["SHOPEE_SHOP_ID"] = str(shop_id)
        os.environ["SHOPEE_REFRESH_TOKEN"] = res["refresh_token"]
    print(f"\n✅ CHAVES_DADOS.env atualizado: SHOPEE_SHOP_ID={shop_id} e SHOPEE_REFRESH_TOKEN novo.")

    shop_id_anterior = shopee_core.SHOP_ID
    shopee_core.SHOP_ID = shop_id
    # Prova de ponta a ponta: renova com o token recém-gravado, como o app fará.
    if not shopee_core.obter_access_token():
        print("⚠️ O token foi gravado, mas a renovação de teste falhou (veja o erro acima).")
        return 1
    print("🎉 Conexão com a Shopee validada. Daqui pra frente a renovação é automática.")
    if shop_id != shop_id_anterior:
        print("ℹ️ O shop_id mudou: se o app estiver aberto, reinicie o run_local.ps1.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
