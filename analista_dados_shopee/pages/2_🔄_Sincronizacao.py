import streamlit as st
import psycopg2
import psycopg2.extras
import pandas as pd
import io
import os
import re
import sys
from datetime import datetime, timedelta
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

def carregar_dataframe_limpo(uploaded_file):
    """Filtro inteligente para pular o cabeçalho 'sujo' e avisos da Shopee"""
    if uploaded_file.name.endswith('.csv'):
        texto = uploaded_file.getvalue().decode('utf-8-sig')
        linhas = texto.splitlines()
        idx_cabecalho = 0
        for i, linha in enumerate(linhas[:20]):
            linha_low = linha.lower()
            if 'id do item' in linha_low or 'id do produto' in linha_low or 'nome do anúncio' in linha_low:
                idx_cabecalho = i
                break
        df = pd.read_csv(io.StringIO("\n".join(linhas[idx_cabecalho:])))
    else:
        df = pd.read_excel(uploaded_file)
        idx_cabecalho = 0
        for i in range(min(15, len(df))):
            valores = str(df.iloc[i].values).lower()
            if 'id do item' in valores or 'id do produto' in valores or 'nome do anúncio' in valores:
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
                    data_val = pd.to_datetime(row[col_data], errors='coerce', format='%d/%m/%Y')
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


def processar_arquivos_marketing(arquivo_trafego, arquivo_ads, data_inicio, data_fim):
    dias_no_periodo = (data_fim - data_inicio).days + 1
    if dias_no_periodo <= 0: return 0, "A Data Final deve ser maior ou igual à Inicial."

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT item_id, LOWER(nome_atual) FROM dim_produtos")
            produtos_db = cur.fetchall()
            
    linhas_trafego, linhas_ads = [], []
    
    # ---------------------------------------------------------
    # CORREÇÃO: Usar um dicionário para agregar as métricas
    # Isso impede a CardinalityViolation agrupando métricas duplicadas
    # ---------------------------------------------------------
    dict_metricas = {}

    def add_metrica(item, data, nome, valor, fonte):
        chave = (item, data, nome, fonte)
        # Se a chave já existe, soma o valor. Se não, inicializa.
        dict_metricas[chave] = dict_metricas.get(chave, 0.0) + float(valor)

    # 1. PLANILHA DE PERFORMANCE ORGÂNICA
    if arquivo_trafego:
        try:
            df_t = carregar_dataframe_limpo(arquivo_trafego)
            
            col_id = next((c for c in df_t.columns if 'id do item' in c or 'id do produto' in c), None)
            col_visitas = next((c for c in df_t.columns if 'visitante' in c or 'visita' in c), None)
            col_carrinho = next((c for c in df_t.columns if 'carrinho' in c), None)
            col_rejeicao = next((c for c in df_t.columns if 'rejeição' in c or 'bounce' in c), None)
            
            for _, row in df_t.iterrows():
                if col_id and pd.notna(row[col_id]) and "dados atuais" not in str(row[col_id]).lower():
                    try:
                        item_id = int(limpar_valor(row[col_id]))
                    except:
                        continue
                else:
                    continue
                
                if not any(item_id == pid for pid, _ in produtos_db):
                    continue 
                
                visitas = int(limpar_valor(row[col_visitas])) if col_visitas else 0
                carrinho = int(limpar_valor(row[col_carrinho])) if col_carrinho else 0
                rejeicao = limpar_valor(row[col_rejeicao]) if col_rejeicao else 0.0
                
                for d in range(dias_no_periodo):
                    dia_registro = data_inicio + timedelta(days=d)
                    valor_visitas = int(visitas/dias_no_periodo)
                    valor_carrinho = int(carrinho/dias_no_periodo)
                    valor_rejeicao = rejeicao / dias_no_periodo if dias_no_periodo > 0 else rejeicao
                    
                    linhas_trafego.append((item_id, dia_registro.date(), valor_visitas, valor_rejeicao, valor_carrinho))

                    # Usa a nova função de agregação
                    add_metrica(item_id, dia_registro.date(), 'visitas_importadas', valor_visitas, arquivo_trafego.name)
                    add_metrica(item_id, dia_registro.date(), 'carrinhos_importados', valor_carrinho, arquivo_trafego.name)
                    add_metrica(item_id, dia_registro.date(), 'rejeicao_importada', valor_rejeicao, arquivo_trafego.name)

                for col in df_t.columns:
                    if col in {col_id, col_visitas, col_carrinho, col_rejeicao}:
                        continue
                    if any(k in col.lower() for k in ['venda','receita','gmv','pedido','ticket','avg','reemb','cancel','devol','margem','custo','gasto','ads','despesa','cpc','ctr','conversao','preco','price','stock','estoque','roas','taxa']):
                        valor = limpar_valor(row[col]) if pd.notna(row[col]) and str(row[col]).strip() not in {'-', ''} else 0.0
                        if valor == 0:
                            continue
                        for d in range(dias_no_periodo):
                            dia_registro = data_inicio + timedelta(days=d)
                            add_metrica(item_id, dia_registro.date(), normalizar_nome_metric(col), valor / dias_no_periodo, arquivo_trafego.name)
        except Exception as e:
            return 0, f"Erro ao ler Tráfego Orgânico: {e}"

    # 2. PLANILHA DE SHOPEE ADS
    if arquivo_ads:
        try:
            df_a = carregar_dataframe_limpo(arquivo_ads)
            
            col_id_ads = next((c for c in df_a.columns if 'id do produto' in c), None)
            col_nome = next((c for c in df_a.columns if 'nome' in c or 'produto' in c or 'anúncio' in c), None)
            col_kw = next((c for c in df_a.columns if 'palavra' in c or 'keyword' in c), None)
            col_imp = next((c for c in df_a.columns if 'impress' in c), None)
            col_cli = next((c for c in df_a.columns if 'clique' in c or 'click' in c), None)
            col_custo = next((c for c in df_a.columns if 'despesa' in c or 'custo' in c or 'gasto' in c), None)
            col_gmv = next((c for c in df_a.columns if 'vgm' in c or 'vendas' in c), None)
            
            for _, row in df_a.iterrows():
                item_id = None
                
                if col_id_ads and pd.notna(row[col_id_ads]) and str(row[col_id_ads]).strip() != '-':
                    try: item_id = int(limpar_valor(row[col_id_ads]))
                    except: pass
                
                if not item_id and col_nome:
                    nome_csv = str(row[col_nome]).lower().strip()
                    for pid, pnome in produtos_db:
                        if pnome in nome_csv or nome_csv in pnome:
                            item_id = pid; break
                        
                if not item_id: continue
                
                kw = str(row[col_kw]) if col_kw and pd.notna(row[col_kw]) and str(row[col_kw]).strip() != '-' else "Ampla/Shop"
                imp = int(limpar_valor(row[col_imp])) if col_imp else 0
                cli = int(limpar_valor(row[col_cli])) if col_cli else 0
                custo = limpar_valor(row[col_custo]) if col_custo else 0.0
                gmv = limpar_valor(row[col_gmv]) if col_gmv else 0.0
                
                for d in range(dias_no_periodo):
                    dia_registro = data_inicio + timedelta(days=d)
                    linhas_ads.append((item_id, kw, dia_registro.date(), int(imp/dias_no_periodo), int(cli/dias_no_periodo), custo/dias_no_periodo, gmv/dias_no_periodo))

                for col in df_a.columns:
                    if col in {col_id_ads, col_nome, col_kw}:
                        continue
                    if any(k in col.lower() for k in ['venda','receita','gmv','pedido','ticket','avg','reemb','cancel','devol','margem','custo','gasto','ads','despesa','cpc','ctr','conversao','preco','price','stock','estoque','roas','taxa','impress','clique']):
                        valor = limpar_valor(row[col]) if pd.notna(row[col]) and str(row[col]).strip() not in {'-', ''} else 0.0
                        if valor == 0:
                            continue
                        for d in range(dias_no_periodo):
                            dia_registro = data_inicio + timedelta(days=d)
                            add_metrica(item_id, dia_registro.date(), normalizar_nome_metric(col), valor / dias_no_periodo, arquivo_ads.name)
        except Exception as e:
            return 0, f"Erro ao ler Arquivo de Ads: {e}"

    # ---------------------------------------------------------
    # Converte o dicionário agregado de volta para a lista esperada
    # ---------------------------------------------------------
    metricas_importadas = [
        (chave[0], chave[1], chave[2], valor, chave[3])
        for chave, valor in dict_metricas.items()
    ]

    # INSERÇÃO PROTEGIDA (Idempotente)
    total_linhas = len(linhas_trafego) + len(linhas_ads)
    if total_linhas > 0:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                for d in range(dias_no_periodo):
                    dia_del = (data_inicio + timedelta(days=d)).date()
                    if arquivo_trafego: cur.execute("DELETE FROM fato_trafego_diario WHERE data = %s", (dia_del,))
                    if arquivo_ads: cur.execute("DELETE FROM fato_ads_palavras_chave WHERE data = %s", (dia_del,))
                
                if linhas_trafego:
                    psycopg2.extras.execute_values(cur, """
                        INSERT INTO fato_trafego_diario (item_id, data, visitantes_unicos, taxa_rejeicao, adicoes_carrinho) VALUES %s
                    """, linhas_trafego)
                
                if linhas_ads:
                    psycopg2.extras.execute_values(cur, """
                        INSERT INTO fato_ads_palavras_chave (item_id, keyword, data, impressoes, cliques, custo_total, gmv_gerado) VALUES %s
                    """, linhas_ads)

                if metricas_importadas:
                    cur.execute("DELETE FROM fato_metricas_produto_importadas WHERE data_registro BETWEEN %s AND %s", (data_inicio.date(), data_fim.date()))
                    psycopg2.extras.execute_values(cur, """
                        INSERT INTO fato_metricas_produto_importadas (item_id, data_registro, metric_name, metric_value, fonte)
                        VALUES %s
                        ON CONFLICT (item_id, data_registro, metric_name, fonte) DO UPDATE SET
                            metric_value = EXCLUDED.metric_value;
                    """, metricas_importadas)
            conn.commit()
            
    return total_linhas, "Sucesso"

# ==============================================================================
# INTERFACE COM ABAS (TABS) E LINKS RÁPIDOS
# ==============================================================================
st.title("🔄 Sincronização e Data Warehouse")
st.markdown("""
Carregue dados de marketing, tráfego e desempenho da Shopee para enriquecer o Data Warehouse.  
O fluxo é compatível com CSVs e XLSX, e os arquivos são processados de forma consistente para alimentar o Cérebro IA.
""")

# Exibe o status atual do banco
col_a, col_b = st.columns(2)
ultima_sync_pedidos = obter_ultima_sincronizacao('PEDIDOS')
ultima_sync_trafego = obter_ultima_sincronizacao('TRAFEGO_ADS')
with col_a: st.info(f"📦 Última extração API (Pedidos): **{ultima_sync_pedidos.strftime('%d/%m/%Y %H:%M') if ultima_sync_pedidos else 'Nunca'}**")
with col_b: st.info(f"📈 Última extração CSV (Marketing): **{ultima_sync_trafego.strftime('%d/%m/%Y') if ultima_sync_trafego else 'Nunca'}**")

st.divider()

# Criação das Abas
arquivo_global = None
aba_principal, aba_global = st.tabs(["⚙️ Motor Principal (API + Produtos)", "📈 Visão Geral da Loja (Dashboard Global)"])

with aba_principal:
    st.markdown("### Atualização de Marketing (Itens Específicos)")
    st.markdown("""
    O Cérebro IA cruza os custos de Ads, tráfego orgânico, vendas e estoque para otimizar a lucratividade.  
    Você pode importar arquivos CSV/XLSX de tráfego orgânico, Ads e performance, desde que contenham o identificador do item/produto.
    """)
    st.info("📌 Arquivos esperados: CSV/XLSX com coluna de item_id ou nome do produto e métricas de tráfego/ads. O sistema tenta reconhecer automaticamente os nomes das colunas mais comuns.")

    hoje = datetime.now()
    data_sugerida_inicio = ultima_sync_trafego if ultima_sync_trafego else (hoje - timedelta(days=30))
    
    periodo_selecionado = st.date_input("📅 Qual foi o período selecionado nos painéis da Shopee?", 
                                        value=(data_sugerida_inicio.date(), hoje.date()), 
                                        max_value=hoje.date())

    col_trafego, col_ads = st.columns(2)
    with col_trafego:
        st.markdown("**1. Orgânico (Performance de produtos / tráfego)")
        st.link_button("🔗 Ir para Business Insights", "https://seller.shopee.com.br/datacenter/product/performance", use_container_width=True)
        st.caption("Use a aba de performance do produto e exporte os dados de visitas, carrinho e rejeição.")
        arquivo_trafego = st.file_uploader("📂 Arraste o CSV/XLSX de Performance Orgânica", type=["csv", "xlsx"], key="upload_trafego")
        
    with col_ads:
        st.markdown("**2. Pago (Ads e palavras-chave)**")
        st.link_button("🔗 Ir para Shopee Ads", "https://seller.shopee.com.br/portal/marketing/pas/index", use_container_width=True)
        st.caption("Use os dados de campanha, palavra-chave, impressões, cliques, custo e GMV.")
        arquivo_ads = st.file_uploader("📂 Arraste o CSV/XLSX de Ads", type=["csv", "xlsx"], key="upload_ads")

    if not arquivo_trafego and not arquivo_ads:
        st.warning("⚠️ Insira pelo menos uma das planilhas para atualizar as métricas do seu negócio. O processamento é opcional para o fluxo de API, mas melhora bastante a análise da IA.")

    datas_validas = isinstance(periodo_selecionado, tuple) and len(periodo_selecionado) == 2

    if st.button("🚀 INICIAR SINCRONIZAÇÃO COMPLETA", type="primary", use_container_width=True, disabled=not (arquivo_trafego or arquivo_ads) or not datas_validas):
        
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
            dt_inicio_pedidos = ultima_sync_pedidos or datetime(2026, 1, 26)
            
            if dt_inicio_pedidos >= agora - timedelta(minutes=10):
                status.update(label="Pedidos já estão atualizados na última hora.", state="complete")
            else:
                blocos = fatiar_periodo(dt_inicio_pedidos, agora)
                barra = st.progress(0)
                total_pedidos = 0
                
                for i, (inicio_bloco, fim_bloco) in enumerate(blocos):
                    res_ped = sincronizar_pedidos(inicio_bloco, fim_bloco)
                    if res_ped["status"] == "sucesso":
                        total_pedidos += res_ped["registros"]
                        registrar_sincronizacao('PEDIDOS', inicio_bloco, fim_bloco, 'SUCESSO', res_ped["registros"])
                    else:
                        st.error("Erro no processamento da API de Pedidos.")
                        break
                    barra.progress((i + 1) / len(blocos))
                    
                status.update(label=f"Motor Financeiro atualizado! ({total_pedidos} novos pedidos)", state="complete")

        with st.status(f"3. Processando Data Warehouse ({dt_inicio_csv.strftime('%d/%m')} a {dt_fim_csv.strftime('%d/%m')})...", expanded=True) as status:
            linhas, msg = processar_arquivos_marketing(arquivo_trafego, arquivo_ads, dt_inicio_csv, dt_fim_csv)
            
            if msg == "Sucesso":
                registrar_sincronizacao('TRAFEGO_ADS', dt_inicio_csv, dt_fim_csv, 'SUCESSO', linhas)
                status.update(label=f"Métricas Inteligentes Consolidadas! ({linhas} registros amarrados)", state="complete")
            else:
                status.update(label=f"Falha no CSV: {msg}", state="error"); st.stop()

        if arquivo_global is not None:
            with st.status("4. Importando visão geral da loja...", expanded=True) as status_global:
                linhas_global, msg_global = processar_arquivo_global(arquivo_global)
                if msg_global == "Sucesso":
                    status_global.update(label=f"Visão geral importada! ({linhas_global} métricas registradas)", state="complete")
                else:
                    status_global.update(label=f"Falha na visão geral: {msg_global}", state="warning")
                
        st.balloons()
        st.success("🎉 Processo Finalizado! O Cérebro IA já pode analisar ROAS, conversão, estoque, preço e performance de cada variação com mais contexto.")

with aba_global:
    st.markdown("### Saúde Geral da Loja (Visão Macros)")
    st.markdown("""
    Importe o arquivo de 'Produto Pago' para alimentar o Cérebro IA com a visão macro da loja.
    O sistema processará o arquivo e atualizará as métricas globais no Data Warehouse.
    """)
    st.link_button("🔗 Ir para Visão Geral", "https://seller.shopee.com.br/datacenter/dashboard", use_container_width=True)
    
    arquivo_global = st.file_uploader("📂 Arraste a planilha 'Produto Pago' (CSV/XLSX)", type=["csv", "xlsx"], key="upload_global")
    
    # --- BOTÃO E FEEDBACK ADICIONADOS ---
    if arquivo_global:
        st.info("💡 Arquivo pronto para processamento.")
        if st.button("🚀 PROCESSAR VISÃO GERAL DA LOJA", type="primary", use_container_width=True):
            with st.status("Processando métricas globais...", expanded=True) as status_global:
                linhas_global, msg_global = processar_arquivo_global(arquivo_global)
                
                if msg_global == "Sucesso":
                    status_global.update(label=f"Visão geral importada! ({linhas_global} métricas registradas)", state="complete")
                    st.balloons()
                else:
                    status_global.update(label=f"Falha na visão geral: {msg_global}", state="error")