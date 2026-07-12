from loguru import logger
import streamlit as st
import psycopg2
import psycopg2.extras
import pandas as pd
import io
import os
import re
import sys
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from dotenv import load_dotenv

# Configuração de caminhos e ambiente
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))
load_dotenv(ROOT_DIR / "CHAVES_DADOS.env")

# Importação dos módulos da API
from workers.sync_catalogo import sincronizar_catalogo
from workers.sync_pedidos import sincronizar_pedidos

st.set_page_config(page_title="Sincronização do DW", page_icon="🔄", layout="wide")

# ==============================================================================
# FUNÇÕES DE BANCO DE DADOS
# ==============================================================================
def get_db_connection():
    try:
        return psycopg2.connect(
            host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"),
            database=os.getenv("POSTGRES_DB"), user=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD")
        )
    except Exception as e:
        st.error(f"🚨 Falha de conexão ao PostgreSQL: {e}")
        st.stop()

def obter_ultima_sincronizacao(modulo):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT data_fim_coleta FROM sys_controle_sync 
                WHERE modulo = %s AND status = 'SUCESSO' 
                ORDER BY data_fim_coleta DESC LIMIT 1;
            """, (modulo,))
            resultado = cur.fetchone()
    return resultado[0] if resultado else None

def registrar_sincronizacao(modulo, data_inicio, data_fim, status, registros):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO sys_controle_sync (modulo, data_inicio_coleta, data_fim_coleta, status, registros_afetados)
                VALUES (%s, %s, %s, %s, %s);
            """, (modulo, data_inicio, data_fim, status, registros))
        conn.commit()

def fatiar_periodo(start_date, end_date, max_dias=14):
    blocos = []
    atual = start_date
    while atual < end_date:
        proximo = min(atual + timedelta(days=max_dias), end_date)
        blocos.append((atual, proximo))
        atual = proximo
    return blocos

# ==============================================================================
# PROCESSADOR INTELIGENTE (Bypass de Arquivos da Shopee)
# ==============================================================================
def limpar_valor(val):
    if pd.isna(val) or val == '-': return 0.0
    if isinstance(val, (int, float)): return float(val)
    val_str = str(val).replace('R$', '').replace('.', '').replace(',', '.').replace('%', '').strip()
    try: return float(val_str)
    except: return 0.0


def limpar_valor_opcional(val):
    """Preserva ausência de dado como NULL; zero continua significando zero medido."""
    if pd.isna(val) or str(val).strip() in {'', '-'}:
        return None
    return limpar_valor(val)


def distribuir_inteiro(total: int | None, dias: int, indice: int) -> int | None:
    """Distribui um total agregado sem perder unidades por arredondamento."""
    if total is None:
        return None
    quociente, resto = divmod(int(total), dias)
    return quociente + (1 if indice < resto else 0)


def distribuir_monetario(valor: float, dias: int, indice: int) -> Decimal:
    """Distribui em centavos e preserva exatamente o total financeiro do período."""
    centavos = int((Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) * 100)
    quociente, resto = divmod(centavos, dias)
    return Decimal(quociente + (1 if indice < resto else 0)) / Decimal(100)

def carregar_dataframe_limpo(uploaded_file):
    """Filtro inteligente para pular o cabeçalho 'sujo' e avisos da Shopee"""
    if uploaded_file.name.endswith('.csv'):
        texto = uploaded_file.getvalue().decode('utf-8-sig')
        linhas = texto.splitlines()
        idx_cabecalho = 0
        for i, linha in enumerate(linhas[:20]):
            linha_low = linha.lower()
            # Adicionado 'nome do produto' para garantir a leitura do arquivo GMV Max Detail
            if 'id do item' in linha_low or 'id do produto' in linha_low or 'nome do anúncio' in linha_low or 'nome do produto' in linha_low:
                idx_cabecalho = i
                break
        df = pd.read_csv(io.StringIO("\n".join(linhas[idx_cabecalho:])))
    else:
        df = pd.read_excel(uploaded_file)
        idx_cabecalho = 0
        for i in range(min(15, len(df))):
            valores = str(df.iloc[i].values).lower()
            if 'id do item' in valores or 'id do produto' in valores or 'nome do anúncio' in valores or 'nome do produto' in valores:
                idx_cabecalho = i
                break
        if idx_cabecalho > 0:
            df.columns = df.iloc[idx_cabecalho]
            df = df[idx_cabecalho+1:].reset_index(drop=True)
            
    df.columns = df.columns.astype(str).str.lower().str.strip()
    return df


def normalizar_nome_metric(coluna):
    nome = re.sub(r'[^a-z0-9]+', '_', coluna.lower()).strip('_')
    return nome or 'metrica_importada'
def processar_arquivo_global(arquivo_global):
    if not arquivo_global:
        return 0, "Nenhum arquivo de visão geral recebido."

    try:
        df = carregar_dataframe_limpo(arquivo_global)
        if df.empty:
            return 0, "Arquivo vazio ou sem conteúdo reconhecido."

        col_data = next((c for c in df.columns if any(k in c.lower() for k in ['data', 'date', 'dia', 'periodo', 'period'])) , None)
        if not col_data:
            return 0, "Não foi possível identificar uma coluna de data no arquivo."

        metricas = []
        for col in df.columns:
            if col == col_data:
                continue
            nome_col = col.lower()
            if not any(k in nome_col for k in ['venda', 'receita', 'gmv', 'lucro', 'margem', 'custo', 'ads', 'visita', 'conversao', 'rejei', 'cancel', 'pedido', 'estoque', 'preco', 'price', 'roas', 'taxa']):
                continue

            for _, row in df.iterrows():
                try:
                    # Melhoria: Deixa o Pandas inferir o formato da data, assumindo dia primeiro
                    data_val = pd.to_datetime(row[col_data], errors='coerce', dayfirst=True)
                    if pd.isna(data_val):
                        continue
                except Exception:
                    continue

                valor = limpar_valor(row[col]) if pd.notna(row[col]) and str(row[col]).strip() not in {'-', ''} else 0.0
                metricas.append((data_val.date(), col, float(valor), arquivo_global.name))

        if not metricas:
            return 0, "Não foram encontradas métricas reconhecíveis para armazenar."

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS fato_visao_geral_loja (
                        data_registro DATE NOT NULL,
                        metric_name VARCHAR(150) NOT NULL,
                        metric_value DECIMAL(12,2) NOT NULL,
                        fonte VARCHAR(255) NOT NULL,
                        PRIMARY KEY (data_registro, metric_name, fonte)
                    );
                """)
                psycopg2.extras.execute_values(cur, """
                    INSERT INTO fato_visao_geral_loja (data_registro, metric_name, metric_value, fonte)
                    VALUES %s
                    ON CONFLICT (data_registro, metric_name, fonte) DO UPDATE SET
                        metric_value = EXCLUDED.metric_value;
                """, [(m[0], m[1], m[2], m[3]) for m in metricas])
            conn.commit()

        return len(metricas), "Sucesso"
    except Exception as e:
        return 0, f"Erro ao processar arquivo global: {e}"


def processar_trafego_organico(arquivo_trafego, data_inicio, data_fim):
    dias_no_periodo = (data_fim - data_inicio).days + 1
    if dias_no_periodo <= 0: return 0, "A Data Final deve ser maior ou igual à Inicial."

    if not arquivo_trafego:
        return 0, "Nenhum arquivo de tráfego fornecido."

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT item_id, LOWER(nome_atual) FROM dim_produtos")
            produtos_db = cur.fetchall()
            
    dict_trafego = {} 
    dict_metricas = {}

    def add_metrica(item, data, nome, valor, fonte):
        chave = (item, data, nome, fonte)
        dict_metricas[chave] = dict_metricas.get(chave, 0.0) + float(valor)

    try:
        df_t = carregar_dataframe_limpo(arquivo_trafego)
        
        # Identificadores e Topo de Funil
        col_id = next((c for c in df_t.columns if 'id do item' in c or 'id do produto' in c), None)
        col_imp_org = next((c for c in df_t.columns if 'impress' in c), None)
        col_cli_org = next((c for c in df_t.columns if 'clique' in c or 'click' in c), None)
        
        # Meio/Fundo de Funil
        col_visitas = next((c for c in df_t.columns if 'visitante' in c or 'visita' in c), None)
        col_carrinho = next((c for c in df_t.columns if 'carrinho' in c), None)
        col_rejeicao = next((c for c in df_t.columns if 'rejeição' in c or 'bounce' in c), None)
        
        for _, row in df_t.iterrows():
            if col_id and pd.notna(row[col_id]) and "dados atuais" not in str(row[col_id]).lower():
                try: item_id = int(limpar_valor(row[col_id]))
                except: continue
            else:
                continue
            
            if not any(item_id == pid for pid, _ in produtos_db):
                continue 
            
            imp_raw = limpar_valor_opcional(row[col_imp_org]) if col_imp_org else None
            cli_raw = limpar_valor_opcional(row[col_cli_org]) if col_cli_org else None
            imp_org = int(imp_raw) if imp_raw is not None else None
            cli_org = int(cli_raw) if cli_raw is not None else None
            visitas = int(limpar_valor(row[col_visitas])) if col_visitas else 0
            carrinho = int(limpar_valor(row[col_carrinho])) if col_carrinho else 0
            rejeicao = limpar_valor(row[col_rejeicao]) if col_rejeicao else 0.0
            
            for d in range(dias_no_periodo):
                dia_registro = data_inicio + timedelta(days=d)
                
                valor_imp = distribuir_inteiro(imp_org, dias_no_periodo, d)
                valor_cli = distribuir_inteiro(cli_org, dias_no_periodo, d)
                valor_visitas = distribuir_inteiro(visitas, dias_no_periodo, d)
                valor_carrinho = distribuir_inteiro(carrinho, dias_no_periodo, d)
                valor_rejeicao = rejeicao
                
                chave_trafego = (item_id, dia_registro.date())
                if chave_trafego not in dict_trafego:
                    dict_trafego[chave_trafego] = [valor_imp, valor_cli, valor_visitas, valor_rejeicao, valor_carrinho, 1]
                else:
                    if valor_imp is not None:
                        dict_trafego[chave_trafego][0] = (dict_trafego[chave_trafego][0] or 0) + valor_imp
                    if valor_cli is not None:
                        dict_trafego[chave_trafego][1] = (dict_trafego[chave_trafego][1] or 0) + valor_cli
                    dict_trafego[chave_trafego][2] += valor_visitas
                    dict_trafego[chave_trafego][3] += valor_rejeicao
                    dict_trafego[chave_trafego][4] += valor_carrinho
                    dict_trafego[chave_trafego][5] += 1

            for col in df_t.columns:
                if col in {col_id, col_imp_org, col_cli_org, col_visitas, col_carrinho, col_rejeicao}:
                    continue
                if any(k in col.lower() for k in ['venda','receita','gmv','pedido','ticket','avg','reemb','cancel','devol','margem','custo','gasto','ads','despesa','cpc','ctr','conversao','preco','price','stock','estoque','roas','taxa']):
                    valor = limpar_valor(row[col]) if pd.notna(row[col]) and str(row[col]).strip() not in {'-', ''} else 0.0
                    if valor == 0: continue
                    for d in range(dias_no_periodo):
                        dia_registro = data_inicio + timedelta(days=d)
                        add_metrica(item_id, dia_registro.date(), normalizar_nome_metric(col), valor / dias_no_periodo, arquivo_trafego.name)
                        
    except Exception as e:
        return 0, f"Erro ao ler Tráfego Orgânico: {e}"

    linhas_trafego = [
        (k[0], k[1], v[0], v[1], v[2], round(v[3] / v[5], 2), v[4], "AGREGADA_PERIODO")
        for k, v in dict_trafego.items()
    ]

    metricas_importadas = [
        (chave[0], chave[1], chave[2], valor, chave[3])
        for chave, valor in dict_metricas.items()
    ]

    total_linhas = len(linhas_trafego)
    if total_linhas > 0:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                if linhas_trafego:
                    psycopg2.extras.execute_values(cur, """
                        INSERT INTO fato_trafego_diario (item_id, data, impressoes, cliques, visitantes_unicos, taxa_rejeicao, adicoes_carrinho, granularidade_origem)
                        VALUES %s
                        ON CONFLICT (item_id, data) DO UPDATE SET
                            impressoes = COALESCE(EXCLUDED.impressoes, fato_trafego_diario.impressoes),
                            cliques = COALESCE(EXCLUDED.cliques, fato_trafego_diario.cliques),
                            visitantes_unicos = EXCLUDED.visitantes_unicos,
                            taxa_rejeicao = EXCLUDED.taxa_rejeicao,
                            adicoes_carrinho = EXCLUDED.adicoes_carrinho,
                            granularidade_origem = EXCLUDED.granularidade_origem;
                    """, linhas_trafego)

                if metricas_importadas:
                    psycopg2.extras.execute_values(cur, """
                        INSERT INTO fato_metricas_produto_importadas (item_id, data_registro, metric_name, metric_value, fonte)
                        VALUES %s
                        ON CONFLICT (item_id, data_registro, metric_name, fonte) DO UPDATE SET
                            metric_value = EXCLUDED.metric_value;
                    """, metricas_importadas)
            conn.commit()
            
    return total_linhas, "Sucesso"


def processar_relatorio_ads_avancado(arquivos_ads, data_inicio, data_fim):
    if not arquivos_ads:
        return 0, "Nenhum arquivo de Ads fornecido."

    if not isinstance(arquivos_ads, list):
        arquivos_ads = [arquivos_ads]

    dias_no_periodo = (data_fim - data_inicio).days + 1
    if dias_no_periodo <= 0:
        return 0, "Data inválida."

    linhas_insercao = []
    
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Garante que o item 0 existe na dimensão de produtos para aceitar os gastos da Loja
            try:
                cur.execute("""
                    INSERT INTO dim_produtos (item_id, nome_atual, status_shopee) 
                    VALUES (0, 'LOJA GLOBAL (ADS DA LOJA)', 'NORMAL') 
                    ON CONFLICT (item_id) DO NOTHING;
                """)
            except Exception as e:
                logger.warning(f"Aviso ao verificar/criar entidade Loja: {e}")
                
            cur.execute("SELECT item_id, LOWER(nome_atual) FROM dim_produtos")
            produtos_db = cur.fetchall()

    for arquivo_ads in arquivos_ads:
        try:
            df = carregar_dataframe_limpo(arquivo_ads)
            if df.empty:
                continue 

            cols = {c.lower().strip(): c for c in df.columns}
            
            # Identificadores mapeados
            col_id = cols.get('id do produto') or cols.get('id do item')
            col_nome = cols.get('nome do anúncio') or cols.get('nome do produto') or cols.get('produto')
            col_metodo_lance = cols.get('método de lance')
            
            # Métricas Core e Ricas
            col_imp = next((cols[c] for c in cols if 'impress' in c), None)
            col_cli = next((cols[c] for c in cols if 'clique' in c or 'click' in c), None)
            col_inv = next((cols[c] for c in cols if 'investimento' in c or 'despesa' in c or 'custo' in c), None)
            col_gmv = next((
                cols[c] for c in cols
                if (('vendas' in c and 'diretas' not in c and 'cupom' not in c) or 'gmv' in c or 'vgm' in c)
            ), None)
            
            col_cart = next((cols[c] for c in cols if 'carrinho' in c and 'taxa' not in c), None)
            col_conv = next((cols[c] for c in cols if 'conversões' in c and 'custo' not in c and 'taxa' not in c), None)
            col_itens = next((cols[c] for c in cols if 'itens vendidos' in c), None)
            col_roas = next((cols[c] for c in cols if 'roas' in c and 'alvo' not in c and 'direto' not in c), None)
            col_acos = next((cols[c] for c in cols if 'acos' in c and 'direto' not in c), None)

            # É um arquivo de detalhes do GMV Max? (Se sim, todos os itens nele são GMV_MAX)
            is_detail_file = 'gmv max' in arquivo_ads.name.lower()

            for _, row in df.iterrows():
                item_id = None
                nome_anuncio_raw = str(row.get(col_nome, "")) if col_nome else ""
                nome_csv_lower = nome_anuncio_raw.lower().strip()
                
                # IDENTIFICAÇÃO ABSOLUTA E SEM TRUNCAMENTO DO GMV MAX
                is_gmv_max = is_detail_file
                if not is_gmv_max and col_metodo_lance and pd.notna(row.get(col_metodo_lance)):
                    if 'gmv max' in str(row[col_metodo_lance]).lower():
                        is_gmv_max = True
                
                if not is_gmv_max:
                    for valor_celula in row.dropna():
                        if 'gmv max' in str(valor_celula).lower():
                            is_gmv_max = True
                            break
                
                # LÓGICA DE ALOCAÇÃO DE IDs E PREVENÇÃO DE DUPLA CONTAGEM
                is_shop_level = False
                if col_id and str(row.get(col_id, '')).strip() == '-':
                    is_shop_level = True
                    
                    if is_gmv_max:
                        # É a linha que totaliza os R$ 80 do GMV Max no arquivo "Dados Gerais".
                        # Ignoramos esta linha, pois os R$ 80 virão diluídos por SKU no arquivo "Detalhes GMV Max".
                        # Se não ignorarmos, o sistema soma os totais duas vezes.
                        continue
                    else:
                        # É uma campanha de Busca da Loja (tradicional).
                        # Não vem nos detalhes, então temos de salvar este dinheiro na entidade Loja!
                        item_id = 0
                
                # Para campanhas de produtos (ou frações de detalhes do GMV Max), extrai o ID numérico
                if not is_shop_level and col_id and pd.notna(row.get(col_id)) and str(row.get(col_id, '')).strip() != '-':
                    try: item_id = int(limpar_valor(row.get(col_id)))
                    except: pass
                
                # Fallback de Mapeamento: Tentar ligar pelo nome do anúncio ao nome do produto na base
                if not item_id and not is_shop_level and col_nome:
                    for pid, pnome in produtos_db:
                        if pnome in nome_csv_lower or nome_csv_lower in pnome:
                            item_id = pid
                            break
                            
                # O derradeiro bloqueio: ignorar lixo não mapeável que a Shopee exporta
                if item_id is None:
                    continue 

                tipo_campanha = 'GMV_MAX' if is_gmv_max else 'PADRAO'

                # Extração Segura e Blindada contra NaNs
                imp_raw = limpar_valor_opcional(row.get(col_imp)) if col_imp else None
                cli_raw = limpar_valor_opcional(row.get(col_cli)) if col_cli else None
                imp = int(imp_raw) if imp_raw is not None else None
                cli = int(cli_raw) if cli_raw is not None else None
                inv = limpar_valor(row.get(col_inv)) if col_inv else 0.0
                gmv = limpar_valor(row.get(col_gmv)) if col_gmv else 0.0
                cart = int(limpar_valor(row.get(col_cart))) if col_cart else 0
                conv = int(limpar_valor(row.get(col_conv))) if col_conv else 0
                itens = int(limpar_valor(row.get(col_itens))) if col_itens else 0
                roas = limpar_valor(row.get(col_roas)) if col_roas else 0.0
                acos = limpar_valor(row.get(col_acos)) if col_acos else 0.0

                # Impede a inserção inútil de linhas vazias, poupando processamento no DW
                if inv == 0 and gmv == 0 and imp in (0, None) and cli in (0, None):
                    continue

                # Rateio Temporal
                for d in range(dias_no_periodo):
                    dia_registro = data_inicio + timedelta(days=d)
                    linhas_insercao.append((
                        item_id, dia_registro.date(), tipo_campanha, nome_anuncio_raw[:250],
                        distribuir_inteiro(imp, dias_no_periodo, d),
                        distribuir_inteiro(cli, dias_no_periodo, d),
                        distribuir_monetario(inv, dias_no_periodo, d), distribuir_monetario(gmv, dias_no_periodo, d),
                        distribuir_inteiro(cart, dias_no_periodo, d), distribuir_inteiro(conv, dias_no_periodo, d), distribuir_inteiro(itens, dias_no_periodo, d),
                        roas, acos, "AGREGADA_PERIODO"
                    ))

        except Exception as e:
            logger.error(f"Erro ao processar um dos arquivos de Ads ({arquivo_ads.name}): {e}")
            continue

    if not linhas_insercao:
         return 0, "Nenhum dado válido extraído dos arquivos."

    # Inserção Atómica e Idempotente no PostgreSQL
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, """
                    INSERT INTO fato_ads_performance_produto 
                    (item_id, data_registro, tipo_campanha, nome_anuncio, impressoes, cliques, investimento, vendas_gmv, adicoes_carrinho, conversoes, itens_vendidos, roas, acos, granularidade_origem)
                    VALUES %s
                    ON CONFLICT (item_id, data_registro, tipo_campanha) DO UPDATE SET
                        impressoes = COALESCE(EXCLUDED.impressoes, fato_ads_performance_produto.impressoes),
                        cliques = COALESCE(EXCLUDED.cliques, fato_ads_performance_produto.cliques),
                        investimento = EXCLUDED.investimento,
                        vendas_gmv = EXCLUDED.vendas_gmv,
                        adicoes_carrinho = EXCLUDED.adicoes_carrinho,
                        conversoes = EXCLUDED.conversoes,
                        itens_vendidos = EXCLUDED.itens_vendidos,
                        roas = EXCLUDED.roas,
                        acos = EXCLUDED.acos,
                        granularidade_origem = EXCLUDED.granularidade_origem;
                """, linhas_insercao)
            conn.commit()
        return len(linhas_insercao), "Sucesso"
    except Exception as e:
        return 0, f"Erro crítico de banco de dados na inserção de Ads: {e}"

# ==============================================================================
# INTERFACE COM ABAS (TABS) E LINKS RÁPIDOS
# ==============================================================================
st.title("🔄 Sincronização e Data Warehouse")
st.markdown("""
Carregue dados de marketing, tráfego e desempenho da Shopee para enriquecer o Data Warehouse.  
O fluxo é compatível com CSVs e XLSX, e os arquivos são processados de forma consistente para alimentar o Cérebro IA.
""")

col_a, col_b, col_c = st.columns(3)
ultima_sync_pedidos = obter_ultima_sincronizacao('PEDIDOS')
ultima_sync_org = obter_ultima_sincronizacao('TRAFEGO_ORG')
ultima_sync_ads = obter_ultima_sincronizacao('ADS_AVANCADO')

with col_a: st.info(f"📦 Pedidos (API): **{ultima_sync_pedidos.strftime('%d/%m %H:%M') if ultima_sync_pedidos else 'Nunca'}**")
with col_b: st.info(f"🌿 Tráfego Orgânico: **{ultima_sync_org.strftime('%d/%m/%Y') if ultima_sync_org else 'Nunca'}**")
with col_c: st.info(f"🎯 Shopee Ads: **{ultima_sync_ads.strftime('%d/%m/%Y') if ultima_sync_ads else 'Nunca'}**")

st.divider()

arquivo_global = None
aba_principal, aba_ads, aba_global = st.tabs([
    "⚙️ Operação & Orgânico (API)", 
    "📢 Shopee Ads Avançado", 
    "📈 Visão Geral da Loja"
])

with aba_principal:
    st.markdown("### 📦 Operação Diária & Performance Orgânica")
    st.markdown("""
    Nesta aba, sincronizamos os pedidos da API e importamos a planilha padrão de **Performance do Produto**. 
    O sistema foca em capturar suas **Visitas, Adições ao Carrinho e Taxa de Rejeição**.
    """)
    st.info("🛡️ **Segurança de Dados (Idempotência):** Você pode reenviar planilhas com datas repetidas ou sobrepostas.")

    hoje = datetime.now()
    data_sugerida_inicio = ultima_sync_org if ultima_sync_org else (hoje - timedelta(days=30))
    periodo_selecionado = st.date_input("📅 Qual foi o período selecionado para exportar a planilha na Shopee?", 
                                        value=(data_sugerida_inicio.date(), hoje.date()), 
                                        max_value=hoje.date())

    st.link_button("🔗 1. Abrir Business Insights > Desempenho do Produto", "https://seller.shopee.com.br/datacenter/product/performance", use_container_width=True)
    arquivo_trafego = st.file_uploader("📂 2. Arraste o arquivo padrão de Performance do Produto aqui", type=["csv", "xlsx"], key="upload_trafego")

    datas_validas = isinstance(periodo_selecionado, tuple) and len(periodo_selecionado) == 2

    if st.button("🚀 INICIAR SINCRONIZAÇÃO COMPLETA (API + Planilha)", type="primary", use_container_width=True, disabled=not datas_validas):
        agora = datetime.now()
        dt_inicio_csv = datetime.combine(periodo_selecionado[0], datetime.min.time())
        dt_fim_csv = datetime.combine(periodo_selecionado[1], datetime.max.time())
        
        with st.status("1. Conectando API: Catálogo e Estoque...", expanded=True) as status:
            res_cat = sincronizar_catalogo()
            if res_cat["status"] == "sucesso":
                status.update(label=f"Catálogo atualizado! ({res_cat['produtos']} mapeados)", state="complete")
            else:
                status.update(label="Falha na API de catálogo.", state="error"); st.stop()

        with st.status("2. Conectando API: Pedidos e Lucro (Escrow)...", expanded=True) as status:
            if ultima_sync_pedidos:
                dt_inicio_pedidos = ultima_sync_pedidos - timedelta(days=4) 
            else:
                dt_inicio_pedidos = datetime(2026, 1, 26)
            
            if ultima_sync_pedidos and ultima_sync_pedidos >= agora - timedelta(minutes=10):
                status.update(label="Pedidos já estão atualizados na última hora.", state="complete")
            else:
                blocos = fatiar_periodo(dt_inicio_pedidos, agora)
                barra = st.progress(0)
                total_pedidos = 0
                
                for i, (inicio_bloco, fim_bloco) in enumerate(blocos):
                    res_ped = sincronizar_pedidos(inicio_bloco, fim_bloco)
                    if res_ped["status"] == "sucesso":
                        total_pedidos += res_ped["registros"]
                        if i == len(blocos) - 1:
                             registrar_sincronizacao('PEDIDOS', ultima_sync_pedidos or dt_inicio_pedidos, agora, 'SUCESSO', total_pedidos)
                    else:
                        st.error("Erro no processamento da API de Pedidos.")
                        break
                    barra.progress((i + 1) / len(blocos))
                status.update(label=f"Motor Financeiro atualizado! (Registros consolidados)", state="complete")

        if arquivo_trafego:
            with st.status(f"3. Processando Tráfego Orgânico ({dt_inicio_csv.strftime('%d/%m')} a {dt_fim_csv.strftime('%d/%m')})...", expanded=True) as status:
                linhas, msg = processar_trafego_organico(arquivo_trafego, dt_inicio_csv, dt_fim_csv)
                if msg == "Sucesso":
                    registrar_sincronizacao('TRAFEGO_ORG', dt_inicio_csv, dt_fim_csv, 'SUCESSO', linhas)
                    status.update(label=f"Tráfego Consolidado! ({linhas} registros normalizados)", state="complete")
                else:
                    status.update(label=f"Falha no CSV: {msg}", state="error"); st.stop()

        st.balloons()
        st.success("🎉 Sincronização API finalizada! Base operacional e financeira atualizada.")

with aba_ads:
    st.markdown("### 🎯 Inteligência de Shopee Ads (GMV Max & Padrão)")
    st.markdown("""
    O sistema extrairá os custos das campanhas Padrão e de GMV Max individualizadas por produto. Evite enviar a aba *Shop GMV Max* geral, use o arquivo de detalhes.
    """)
    st.info("🛡️ **Idempotente:** Pode exportar os últimos 30 dias todos os dias sem perigo.")
    
    st.link_button("🔗 Abrir Painel do Shopee Ads", "https://seller.shopee.com.br/portal/marketing/pas/index", use_container_width=True)
    
    col_data_ads, col_upload_geral, col_upload_gmv = st.columns([1, 1.5, 1.5])
    with col_data_ads:
        hoje = datetime.now()
        data_sugerida_ads = ultima_sync_ads if ultima_sync_ads else (hoje - timedelta(days=7))
        periodo_ads = st.date_input("📅 Qual o período selecionado?", 
                                     value=(data_sugerida_ads.date(), hoje.date()), 
                                     max_value=hoje.date(),
                                     key="data_input_ads")
                                     
    with col_upload_geral:
        arquivo_ads_geral = st.file_uploader("📂 1. Dados Gerais de Anúncios", type=["csv", "xlsx"], key="upload_ads_geral")
        
    with col_upload_gmv:
        arquivo_ads_gmv_detalhe = st.file_uploader("📂 2. Shop GMV Max (Dados de Detalhes)", type=["csv", "xlsx"], key="upload_ads_gmv_detail")

    datas_ads_validas = isinstance(periodo_ads, tuple) and len(periodo_ads) == 2
    botoes_ok = arquivo_ads_geral is not None or arquivo_ads_gmv_detalhe is not None

    if st.button("🧠 PROCESSAR INTELIGÊNCIA DE ADS", type="primary", use_container_width=True, disabled=not botoes_ok or not datas_ads_validas):
        dt_inicio_ads = datetime.combine(periodo_ads[0], datetime.min.time())
        dt_fim_ads = datetime.combine(periodo_ads[1], datetime.max.time())
        
        with st.status(f"Mapeando campanhas ({dt_inicio_ads.strftime('%d/%m')} a {dt_fim_ads.strftime('%d/%m')})...", expanded=True) as status_ads:
            linhas_ads, msg_ads = processar_relatorio_ads_avancado(arquivo_ads_geral, arquivo_ads_gmv_detalhe, dt_inicio_ads, dt_fim_ads)
            
            if msg_ads == "Sucesso":
                registrar_sincronizacao('ADS_AVANCADO', dt_inicio_ads, dt_fim_ads, 'SUCESSO', linhas_ads)
                status_ads.update(label=f"Análise Concluída! Foram injetados {linhas_ads} dias-registro de inteligência.", state="complete")
                st.balloons()
            else:
                status_ads.update(label=f"Aviso de leitura: {msg_ads}", state="error")

with aba_global:
    st.markdown("### 📈 Saúde Geral da Loja (Dashboard Macro)")
    st.markdown("Esta sessão captura as métricas totais da sua loja para comparar o faturamento geral com os custos e o tráfego total.")
    st.info("🛡️ **Idempotente:** Se subir os mesmos dias, subscrevemos com dados mais recentes.")

    st.link_button("🔗 Abrir Painel de Visão Geral", "https://seller.shopee.com.br/datacenter/dashboard", use_container_width=True)
    
    arquivo_global = st.file_uploader("📂 Arraste a planilha de Visão Geral exportada", type=["csv", "xlsx"], key="upload_global")
    
    if arquivo_global:
        if st.button("🚀 PROCESSAR VISÃO GERAL DA LOJA", type="primary", use_container_width=True):
            with st.status("Consolidando métricas globais e alimentando o DW...", expanded=True) as status_global:
                linhas_global, msg_global = processar_arquivo_global(arquivo_global)
                
                if msg_global == "Sucesso":
                    status_global.update(label=f"Visão geral importada com sucesso! ({linhas_global} métricas atualizadas)", state="complete")
                    st.balloons()
                else:
                    status_global.update(label=f"Falha na importação da visão geral: {msg_global}", state="error")

# ==============================================================================
# INTERFACE COM ABAS (TABS) E LINKS RÁPIDOS
# ==============================================================================
st.title("🔄 Sincronização e Data Warehouse")
st.markdown("""
Carregue dados de marketing, tráfego e desempenho da Shopee para enriquecer o Data Warehouse.  
O fluxo é compatível com CSVs e XLSX, e os arquivos são processados de forma consistente para alimentar o Cérebro IA.
""")

# Exibe o status atual do banco
col_a, col_b, col_c = st.columns(3)
ultima_sync_pedidos = obter_ultima_sincronizacao('PEDIDOS')
ultima_sync_org = obter_ultima_sincronizacao('TRAFEGO_ORG')
ultima_sync_ads = obter_ultima_sincronizacao('ADS_AVANCADO')

with col_a: st.info(f"📦 Pedidos (API): **{ultima_sync_pedidos.strftime('%d/%m %H:%M') if ultima_sync_pedidos else 'Nunca'}**")
with col_b: st.info(f"🌿 Tráfego Orgânico: **{ultima_sync_org.strftime('%d/%m/%Y') if ultima_sync_org else 'Nunca'}**")
with col_c: st.info(f"🎯 Shopee Ads: **{ultima_sync_ads.strftime('%d/%m/%Y') if ultima_sync_ads else 'Nunca'}**")

st.divider()

# Criação das Abas
arquivo_global = None
aba_principal, aba_ads, aba_global = st.tabs([
    "⚙️ Operação & Orgânico (API)", 
    "📢 Shopee Ads Avançado", 
    "📈 Visão Geral da Loja"
])

with aba_principal:
    st.markdown("### 📦 Operação Diária & Performance Orgânica")
    st.markdown("""
    Nesta aba, sincronizamos os pedidos da API e importamos a planilha padrão de **Performance do Produto**. 
    O sistema foca em capturar suas **Visitas, Adições ao Carrinho e Taxa de Rejeição** para entender a saúde orgânica da loja.
    """)
    
    st.info("""
    🛡️ **Segurança de Dados (Idempotência):** Você pode reenviar planilhas com datas repetidas ou sobrepostas. O sistema é inteligente: ele apenas atualiza os registros existentes com as informações mais recentes.
    """)

    hoje = datetime.now()
    data_sugerida_inicio = ultima_sync_org if ultima_sync_org else (hoje - timedelta(days=30))
    
    periodo_selecionado = st.date_input("📅 Qual foi o período selecionado para exportar a planilha na Shopee?", 
                                        value=(data_sugerida_inicio.date(), hoje.date()), 
                                        max_value=hoje.date())

    st.markdown("#### 📥 Como exportar a planilha de Performance correta:")
    st.markdown("""
    1. Acesse o painel pelo botão abaixo. Ele abrirá diretamente a aba **Informações Gerenciais > Produto > Performance do Produto**.
    2. No filtro de calendário (Período dos Dados) no topo, selecione o mesmo período que você escolheu acima.
    3. Na seção "Desempenho do Produto" (lista com os itens), clique no botão azul **Exportar**.
    4. Suba o arquivo Excel/CSV gerado aqui.
    """)
    
    st.link_button("🔗 1. Abrir Business Insights > Desempenho do Produto", "https://seller.shopee.com.br/datacenter/product/performance", use_container_width=True)
    
    arquivo_trafego = st.file_uploader("📂 2. Arraste o arquivo padrão de Performance do Produto aqui", type=["csv", "xlsx"], key="upload_trafego")

    datas_validas = isinstance(periodo_selecionado, tuple) and len(periodo_selecionado) == 2

    if st.button("🚀 INICIAR SINCRONIZAÇÃO COMPLETA (API + Planilha)", type="primary", use_container_width=True, disabled=not datas_validas):
        
        agora = datetime.now()
        dt_inicio_csv = datetime.combine(periodo_selecionado[0], datetime.min.time())
        dt_fim_csv = datetime.combine(periodo_selecionado[1], datetime.max.time())
        
        with st.status("1. Conectando API: Catálogo e Estoque...", expanded=True) as status:
            res_cat = sincronizar_catalogo()
            if res_cat["status"] == "sucesso":
                status.update(label=f"Catálogo atualizado! ({res_cat['produtos']} mapeados)", state="complete")
            else:
                status.update(label="Falha na API de catálogo.", state="error"); st.stop()

        with st.status("2. Conectando API: Pedidos e Lucro (Escrow)...", expanded=True) as status:
            if ultima_sync_pedidos:
                dt_inicio_pedidos = ultima_sync_pedidos - timedelta(days=4) 
            else:
                dt_inicio_pedidos = datetime(2026, 1, 26)
            
            if ultima_sync_pedidos and ultima_sync_pedidos >= agora - timedelta(minutes=10):
                status.update(label="Pedidos já estão atualizados na última hora.", state="complete")
            else:
                blocos = fatiar_periodo(dt_inicio_pedidos, agora)
                barra = st.progress(0)
                total_pedidos = 0
                
                for i, (inicio_bloco, fim_bloco) in enumerate(blocos):
                    res_ped = sincronizar_pedidos(inicio_bloco, fim_bloco)
                    if res_ped["status"] == "sucesso":
                        total_pedidos += res_ped["registros"]
                        if i == len(blocos) - 1:
                             registrar_sincronizacao('PEDIDOS', ultima_sync_pedidos or dt_inicio_pedidos, agora, 'SUCESSO', total_pedidos)
                    else:
                        st.error("Erro no processamento da API de Pedidos.")
                        break
                    barra.progress((i + 1) / len(blocos))
                    
                status.update(label=f"Motor Financeiro atualizado! (Registros consolidados)", state="complete")

        if arquivo_trafego:
            with st.status(f"3. Processando Tráfego Orgânico ({dt_inicio_csv.strftime('%d/%m')} a {dt_fim_csv.strftime('%d/%m')})...", expanded=True) as status:
                linhas, msg = processar_trafego_organico(arquivo_trafego, dt_inicio_csv, dt_fim_csv)
                
                if msg == "Sucesso":
                    registrar_sincronizacao('TRAFEGO_ORG', dt_inicio_csv, dt_fim_csv, 'SUCESSO', linhas)
                    status.update(label=f"Tráfego Consolidado! ({linhas} registros processados e normalizados)", state="complete")
                else:
                    status.update(label=f"Falha no CSV: {msg}", state="error"); st.stop()

        st.balloons()
        st.success("🎉 Sincronização API finalizada! Sua base operacional e financeira está atualizada.")


with aba_ads:
    st.markdown("### 🎯 Inteligência de Shopee Ads (GMV Max & Padrão)")
    st.markdown("""
    Esta sessão alimenta o Data Warehouse com dados de campanhas pagas. Agora **aceita múltiplos arquivos simultaneamente**.
    O sistema extrairá os custos totais da loja (GMV Max Global) e os detalhes de cada produto.
    """)
    
    st.info("🛡️ **Idempotente:** Pode enviar arquivos do mês todo sem medo de duplicação de gastos.")
    
    st.markdown("#### 📥 Passo a Passo para Exportação Perfeita:")
    st.markdown("""
    1. Abra a **Central de Marketing** > **Shopee Ads**.
    2. Role a página até encontrar a tabela **Todos os Anúncios de Produtos**.
    3. Defina o calendário e ative TODAS as métricas em "Diagnóstico".
    4. Clique em Exportar e baixe o arquivo **"Dados Gerais de Anúncios"**.
    5. Se você roda GMV MAX exporte tambem o **"Dados do GMV MAX"** na mesma página.
    6. **Arraste todos os arquivos baixados de uma só vez na caixa abaixo.**
    """)
    
    st.link_button("🔗 1. Abrir Painel do Shopee Ads", "https://seller.shopee.com.br/portal/marketing/pas/index", use_container_width=True)
    
    col_data_ads, col_upload_ads = st.columns([1, 2])
    with col_data_ads:
        hoje = datetime.now()
        data_sugerida_ads = ultima_sync_ads if ultima_sync_ads else (hoje - timedelta(days=7))
        periodo_ads = st.date_input("📅 Qual o período selecionado no Shopee Ads?", 
                                     value=(data_sugerida_ads.date(), hoje.date()), 
                                     max_value=hoje.date(),
                                     key="data_input_ads")
                                     
    with col_upload_ads:
        # ATUALIZAÇÃO CRÍTICA: accept_multiple_files=True
        arquivos_ads_avancado = st.file_uploader("📂 2. Arraste todos os arquivos de Ads aqui", type=["csv", "xlsx"], key="upload_ads_avancado", accept_multiple_files=True)

    datas_ads_validas = isinstance(periodo_ads, tuple) and len(periodo_ads) == 2

    if st.button("🧠 PROCESSAR INTELIGÊNCIA DE ADS", type="primary", use_container_width=True, disabled=not arquivos_ads_avancado or not datas_ads_validas):
        dt_inicio_ads = datetime.combine(periodo_ads[0], datetime.min.time())
        dt_fim_ads = datetime.combine(periodo_ads[1], datetime.max.time())
        
        with st.status(f"Mapeando campanhas de {len(arquivos_ads_avancado)} arquivo(s)... ({dt_inicio_ads.strftime('%d/%m')} a {dt_fim_ads.strftime('%d/%m')})", expanded=True) as status_ads:
            linhas_ads, msg_ads = processar_relatorio_ads_avancado(arquivos_ads_avancado, dt_inicio_ads, dt_fim_ads)
            
            if msg_ads == "Sucesso":
                registrar_sincronizacao('ADS_AVANCADO', dt_inicio_ads, dt_fim_ads, 'SUCESSO', linhas_ads)
                status_ads.update(label=f"Análise Concluída! Foram injetados {linhas_ads} dias-registro de inteligência.", state="complete")
                st.balloons()
            else:
                status_ads.update(label=f"Aviso de leitura: {msg_ads}", state="error")

with aba_global:
    st.markdown("### 📈 Saúde Geral da Loja (Dashboard Macro)")
    st.markdown("""
    Esta sessão captura as métricas totais da sua loja para comparar o faturamento geral com os custos e o tráfego total.
    """)
    st.info("🛡️ **Idempotente:** Se subir os mesmos dias, o Data Warehouse entende e apenas subscreve com os dados mais consolidados.")

    st.markdown("#### 📥 Como extrair a Visão Geral:")
    st.markdown("""
    1. Entre em **Informações Gerenciais** usando o botão abaixo.
    2. No menu lateral, clique em **Painel**.
    3. Logo abaixo das abas, garanta que você está na aba primária chamada **Visão Geral** (Overview).
    4. Selecione o período no calendário e clique em **Exportar**.
    """)

    st.link_button("🔗 1. Abrir Painel de Visão Geral", "https://seller.shopee.com.br/datacenter/dashboard", use_container_width=True)
    
    arquivo_global = st.file_uploader("📂 2. Arraste a planilha de Visão Geral exportada", type=["csv", "xlsx"], key="upload_global")
    
    if arquivo_global:
        st.info("💡 Arquivo carregado na memória, pronto para injeção.")
        if st.button("🚀 PROCESSAR VISÃO GERAL DA LOJA", type="primary", use_container_width=True):
            with st.status("Consolidando métricas globais e alimentando o DW...", expanded=True) as status_global:
                linhas_global, msg_global = processar_arquivo_global(arquivo_global)
                
                if msg_global == "Sucesso":
                    status_global.update(label=f"Visão geral importada com sucesso! ({linhas_global} métricas registradas/atualizadas)", state="complete")
                    st.balloons()
                else:
                    status_global.update(label=f"Falha na importação da visão geral: {msg_global}", state="error")
