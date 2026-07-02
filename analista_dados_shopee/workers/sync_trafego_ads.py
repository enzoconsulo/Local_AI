import os
import sys
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import execute_values
from loguru import logger
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

load_dotenv(ROOT_DIR / "CHAVES_DADOS.env")
from utils.shopee_core import chamar_shopee_api

# Sensores Globais: A Shopee permite puxar estes dados para esta conta?
PERMISSAO_TRAFEGO = True 
PERMISSAO_ADS = True

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"),
        database=os.getenv("POSTGRES_DB"), user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD")
    )

def obter_itens_ativos_do_banco():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT item_id FROM dim_produtos WHERE status_shopee = 'NORMAL';")
        itens = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        return itens
    except Exception as e:
        logger.error(f"Erro ao buscar itens ativos: {e}")
        return []

def obter_trafego_itens(item_ids, data_alvo):
    global PERMISSAO_TRAFEGO
    if not PERMISSAO_TRAFEGO:
        return [] # Ignora silenciosamente se a Shopee bloqueou antes
        
    start_time = int(data_alvo.replace(hour=0, minute=0, second=0).timestamp())
    end_time = int(data_alvo.replace(hour=23, minute=59, second=59).timestamp())
    path_insight = "/api/v2/insight/get_item_stat" 
    dados_trafego = []
    
    lotes = [item_ids[i:i + 50] for i in range(0, len(item_ids), 50)]
    for lote in lotes:
        params = {"item_id_list": ",".join(map(str, lote)), "start_time": start_time, "end_time": end_time}
        response = chamar_shopee_api(path_insight, params)
        
        if response is None:
            logger.warning("A Shopee não liberou a API de Tráfego para esta conta. Pulando métricas de visitantes...")
            PERMISSAO_TRAFEGO = False
            return []
            
        if response and "item_stat_list" in response:
            for stat in response["item_stat_list"]:
                dados_trafego.append({
                    "item_id": stat["item_id"], 
                    "data": data_alvo.strftime('%Y-%m-%d'),
                    "visitantes_unicos": stat.get("visitors", 0), 
                    "taxa_rejeicao": stat.get("bounce_rate", 0.0),
                    "adicoes_carrinho": stat.get("add_to_cart_units", 0)
                })
    return dados_trafego

def obter_performance_ads(item_ids, data_alvo):
    global PERMISSAO_ADS
    if not PERMISSAO_ADS:
        return []

    start_date = data_alvo.strftime('%Y-%m-%d')
    path_ads = "/api/v2/ads/get_keyword_stat" 
    dados_ads = []
    
    for item_id in item_ids:
        params = {"item_id": item_id, "start_date": start_date, "end_date": start_date}
        response = chamar_shopee_api(path_ads, params)
        
        # SENSOR DE ADS: Se a Shopee der block, ele ignora silenciosamente daqui pra frente
        if response is None:
            logger.warning("A Shopee não liberou a API de Ads para esta conta. Pulando anúncios...")
            PERMISSAO_ADS = False
            return []
            
        if response and "keyword_list" in response:
            for kw in response["keyword_list"]:
                dados_ads.append({
                    "item_id": item_id, 
                    "keyword": kw["keyword"], 
                    "data": start_date,
                    "impressoes": kw.get("impressions", 0), 
                    "cliques": kw.get("clicks", 0),
                    "custo_total": kw.get("expense", 0.0), 
                    "gmv_gerado": kw.get("direct_gmv", 0.0)
                })
    return dados_ads

def salvar_metricas_no_banco(trafego, ads, data_alvo):
    data_str = data_alvo.strftime('%Y-%m-%d')
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        if trafego:
            cur.execute("DELETE FROM fato_trafego_diario WHERE data = %s;", (data_str,))
            query_trafego = "INSERT INTO fato_trafego_diario (item_id, data, visitantes_unicos, taxa_rejeicao, adicoes_carrinho) VALUES %s;"
            execute_values(cur, query_trafego, [tuple(t.values()) for t in trafego])
            
        if ads:
            cur.execute("DELETE FROM fato_ads_palavras_chave WHERE data = %s;", (data_str,))
            query_ads = "INSERT INTO fato_ads_palavras_chave (item_id, keyword, data, impressoes, cliques, custo_total, gmv_gerado) VALUES %s;"
            execute_values(cur, query_ads, [tuple(a.values()) for a in ads])
            
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Falha ao gravar métricas de {data_str}: {e}")
        return False

# ==============================================================================
# FUNÇÃO EXPORTADA PARA O STREAMLIT
# ==============================================================================
def sincronizar_trafego_ads(data_inicio: datetime, data_fim: datetime):
    ids_ativos = obter_itens_ativos_do_banco()
    
    if not ids_ativos:
        return {"status": "erro", "registros": 0, "msg": "Nenhum produto ativo encontrado no banco."}
        
    delta = data_fim - data_inicio
    total_registros = 0
    
    for i in range(delta.days + 1):
        dia_atual = data_inicio + timedelta(days=i)
        logger.info(f"Processando Ads/Tráfego para: {dia_atual.strftime('%Y-%m-%d')}")
        
        try:
            trafego_dia = obter_trafego_itens(ids_ativos, dia_atual)
            ads_dia = obter_performance_ads(ids_ativos, dia_atual)
            
            if trafego_dia or ads_dia:
                sucesso = salvar_metricas_no_banco(trafego_dia, ads_dia, dia_atual)
                if sucesso:
                    total_registros += (len(trafego_dia) + len(ads_dia))
        except Exception as e:
            logger.warning(f"Falha ao processar dia {dia_atual.strftime('%Y-%m-%d')}. Erro: {e}")
            continue 
                
    return {"status": "sucesso", "registros": total_registros}