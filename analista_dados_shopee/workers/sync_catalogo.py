import sys
import time
from datetime import date
from psycopg2.extras import execute_values
from loguru import logger
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))
load_dotenv(ROOT_DIR / "CHAVES_DADOS.env")

# Corrigido o caminho do import para refletir a estrutura local correta
from utils.shopee_core import chamar_shopee_api
from utils.db_pool import get_connection

def obter_lista_itens():
    """Lista os anúncios NORMAL. Retorna (item_ids, listagem_completa):
    listagem_completa=False quando a paginação foi interrompida por falha de
    API — nesse caso a lista NÃO pode ser usada para marcar produtos como
    fora do ar (marcaria produtos vivos por engano)."""
    logger.info("Buscando lista de anúncios ativos na Shopee...")
    path = "/api/v2/product/get_item_list"
    offset = 0
    page_size = 50
    item_ids = []
    listagem_completa = True

    while True:
        params = {"offset": offset, "page_size": page_size, "item_status": "NORMAL"}
        response = chamar_shopee_api(path, params)
        if response is None:
            listagem_completa = False
            logger.warning("Paginação do catálogo interrompida por falha de API; a lista pode estar incompleta.")
            break

        itens_pagina = response.get("item", [])
        if not itens_pagina: break

        item_ids.extend([item["item_id"] for item in itens_pagina])
        if not response.get("has_next_page"): break
        offset += page_size

    logger.success(f"Foram encontrados {len(item_ids)} anúncios raiz.")
    return item_ids, listagem_completa

def obter_detalhes_e_variacoes(item_ids):
    logger.info("Buscando detalhes e variações (Models) de cada anúncio...")
    path_base_info = "/api/v2/product/get_item_base_info"
    path_model_list = "/api/v2/product/get_model_list"
    
    produtos, variacoes = [], []
    lotes = [item_ids[i:i + 50] for i in range(0, len(item_ids), 50)]
    
    for lote in lotes:
        params = {"item_id_list": ",".join(map(str, lote))}
        info_response = chamar_shopee_api(path_base_info, params)
        info_dict = {}
        
        if info_response and "item_list" in info_response:
            for item in info_response["item_list"]:
                info_dict[item["item_id"]] = item
                
                # INJEÇÃO MIGRATION 02: Puxando Estrelas, Likes e Prazo
                estrelas = item.get("item_rating", {}).get("rating_star", 0.0)
                likes = item.get("likes", 0)
                dias_preparo = item.get("days_to_ship", 3)

                # MIGRATION 15: capa do anúncio (1ª imagem) — a mesma foto
                # identifica o produto (e todas as suas variações) na UI.
                lista_imagens = (item.get("image") or {}).get("image_url_list") or []
                imagem_url = lista_imagens[0] if lista_imagens else None

                produtos.append({
                    "item_id": item["item_id"],
                    "nome_atual": item["item_name"],
                    "category_id": item["category_id"],
                    "status_shopee": item["item_status"],
                    "data_criacao": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(item["create_time"])),
                    "nota_media_estrelas": estrelas,
                    "likes_count": likes,
                    "dias_pre_encomenda": dias_preparo,
                    "imagem_url": imagem_url
                })
        
        for i_id in lote:
            model_response = chamar_shopee_api(path_model_list, {"item_id": i_id})
            models = model_response.get("model", []) if model_response else []
            
            if not models:
                # O produto não tem variações (Item Base)
                base_info = info_dict.get(i_id, {})
                base_price = base_info.get("price_info", [{}])[0].get("current_price", 0)
                base_sku = base_info.get("item_sku", "")
                
                # INJEÇÃO MIGRATION 02: Puxando Estoque de anúncio sem variação
                base_stock = base_info.get("stock_info", [{}])[0].get("normal_stock", 0)
                
                variacoes.append({
                    "model_id": i_id, "item_id": i_id, "nome_variacao": "Padrão/Única",
                    "sku_variacao": base_sku, "preco_venda_atual": base_price, "estoque_shopee": base_stock
                })
            else:
                for model in models:
                    # INJEÇÃO MIGRATION 02: Puxando Estoque de cada variação
                    var_stock = model.get("stock_info", [{}])[0].get("normal_stock", 0)
                    
                    variacoes.append({
                        "model_id": model["model_id"], "item_id": i_id,
                        "nome_variacao": model["model_name"] if model["model_name"] else "Padrão",
                        "sku_variacao": model["model_sku"], "preco_venda_atual": model["price_info"][0]["current_price"],
                        "estoque_shopee": var_stock
                    })
            time.sleep(0.2)
            
    return produtos, variacoes

def garantir_tabela_historico_variacoes(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS fato_historico_variacoes (
                model_id BIGINT NOT NULL REFERENCES dim_variacoes(model_id) ON DELETE CASCADE,
                data_registro DATE NOT NULL,
                preco_venda_atual DECIMAL(10,2),
                estoque_shopee INTEGER DEFAULT 0,
                PRIMARY KEY (model_id, data_registro)
            );
            CREATE INDEX IF NOT EXISTS idx_fato_historico_variacoes_model_data
            ON fato_historico_variacoes (model_id, data_registro DESC);
        """)


def salvar_no_banco(produtos, variacoes):
    logger.info("Iniciando sincronização com o PostgreSQL (Catálogo)...")
    try:
        with get_connection() as conn:
            garantir_tabela_historico_variacoes(conn)
            cur = conn.cursor()

            # ATUALIZADO MIGRATION 02: Inserindo as métricas extras do Produto
            query_produtos = """
                INSERT INTO dim_produtos (item_id, nome_atual, category_id, status_shopee, data_criacao, nota_media_estrelas, likes_count, dias_pre_encomenda, imagem_url)
                VALUES %s ON CONFLICT (item_id) DO UPDATE SET
                    nome_atual = EXCLUDED.nome_atual, category_id = EXCLUDED.category_id,
                    status_shopee = EXCLUDED.status_shopee, nota_media_estrelas = EXCLUDED.nota_media_estrelas,
                    likes_count = EXCLUDED.likes_count, dias_pre_encomenda = EXCLUDED.dias_pre_encomenda,
                    imagem_url = COALESCE(EXCLUDED.imagem_url, dim_produtos.imagem_url);
            """
            valores_produtos = [(p['item_id'], p['nome_atual'], p['category_id'], p['status_shopee'], p['data_criacao'], p['nota_media_estrelas'], p['likes_count'], p['dias_pre_encomenda'], p.get('imagem_url')) for p in produtos]
            execute_values(cur, query_produtos, valores_produtos)

            # ATUALIZADO MIGRATION 02: Inserindo o estoque_shopee na variação
            query_variacoes = """
                INSERT INTO dim_variacoes (model_id, item_id, nome_variacao, sku_variacao, preco_venda_atual, estoque_shopee)
                VALUES %s ON CONFLICT (model_id) DO UPDATE SET
                    nome_variacao = EXCLUDED.nome_variacao, sku_variacao = EXCLUDED.sku_variacao,
                    preco_venda_atual = EXCLUDED.preco_venda_atual, estoque_shopee = EXCLUDED.estoque_shopee;
            """
            valores_variacoes = [(v['model_id'], v['item_id'], v['nome_variacao'], v['sku_variacao'], v['preco_venda_atual'], v['estoque_shopee']) for v in variacoes]
            execute_values(cur, query_variacoes, valores_variacoes)

            query_historico = """
                INSERT INTO fato_historico_variacoes (model_id, data_registro, preco_venda_atual, estoque_shopee)
                VALUES %s
                ON CONFLICT (model_id, data_registro) DO UPDATE SET
                    preco_venda_atual = EXCLUDED.preco_venda_atual,
                    estoque_shopee = EXCLUDED.estoque_shopee;
            """
            valores_historico = [(v['model_id'], date.today(), v['preco_venda_atual'], v['estoque_shopee']) for v in variacoes]
            if valores_historico:
                execute_values(cur, query_historico, valores_historico)
            cur.close()

        logger.success(f"Catálogo salvo: {len(produtos)} Produtos e {len(variacoes)} Variações.")
        return True
    except Exception as e:
        logger.error(f"Falha ao gravar catálogo: {e}")
        return False

def marcar_produtos_fora_do_ar(item_ids_ativos):
    """Produtos que sumiram da listagem NORMAL (excluídos/despublicados na
    Shopee) saem do radar do Cérebro IA. Sem isto, um SKU morto continuaria
    'NORMAL' no banco e seria auditado (e custaria tokens) para sempre.
    Só deve ser chamada com a listagem paginada até o fim."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE dim_produtos
                    SET status_shopee = 'NAO_LISTADO'
                    WHERE status_shopee = 'NORMAL'
                      AND item_id <> 0
                      AND NOT (item_id = ANY(%s));
                """, (list(item_ids_ativos),))
                return cur.rowcount
    except Exception as e:
        logger.warning(f"Não foi possível marcar produtos fora do ar: {e}")
        return 0


# ==============================================================================
# FUNÇÃO EXPORTADA PARA O STREAMLIT
# ==============================================================================
def sincronizar_catalogo():
    """Função principal a ser chamada pelo botão de sincronização."""
    lista_ids, listagem_completa = obter_lista_itens()
    if lista_ids:
        produtos_extraidos, variacoes_extraidas = obter_detalhes_e_variacoes(lista_ids)
        sucesso = salvar_no_banco(produtos_extraidos, variacoes_extraidas)
        if sucesso and listagem_completa:
            desativados = marcar_produtos_fora_do_ar(lista_ids)
            if desativados:
                logger.info(f"{desativados} produto(s) saíram da listagem NORMAL e foram marcados como NAO_LISTADO.")
        return {"status": "sucesso" if sucesso else "erro", "produtos": len(produtos_extraidos)}
    return {"status": "erro", "produtos": 0}