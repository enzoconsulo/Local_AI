import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Carrega o ambiente
ROOT_DIR = Path(__file__).resolve().parent
sys.path.append(str(ROOT_DIR))
load_dotenv(ROOT_DIR / "CHAVES_DADOS.env")

from utils.shopee_core import chamar_shopee_api

def testar_conexao():
    print("⏳ Batendo na porta da Shopee API v2...")
    
    # Endpoint inofensivo que apenas lê o perfil da sua loja
    path = "/api/v2/shop/get_shop_info"
    
    resposta = chamar_shopee_api(path, method="GET")
    
    if resposta:
        print("\n✅ SUCESSO ABSOLUTO! A ponte está aberta.")
        print(f"📦 Nome da Loja: {resposta.get('shop_name')}")
        print(f"🌍 Região: {resposta.get('region')}")
        print(f"🟢 Status: {resposta.get('status')}")
    else:
        print("\n❌ FALHA. A Shopee não deixou entrar. Verifique o CHAVES_DADOS.env.")

if __name__ == "__main__":
    testar_conexao()