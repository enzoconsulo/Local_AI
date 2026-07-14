"""
pages/2_🔄_Sincronizacao.py
============================
ETL do Data Warehouse: pedidos/catálogo via API Shopee + importação das
planilhas exportadas do Seller Center (Performance do Produto, Shopee Ads,
Visão Geral da Loja).

Garantias deste módulo:
  - Idempotência por linha (UPSERT) e por arquivo (hash SHA-256 em
    sys_lotes_importacao — migração 12).
  - Granularidade honesta: uploads de 1 dia são gravados como DIARIA,
    períodos maiores como AGREGADA_PERIODO (rateio sem perda de totais).
  - Aviso quando um novo período cruza importações antigas com rateio
    diferente (evita distorção silenciosa das janelas 7d/30d do Cérebro IA).
"""

from loguru import logger
import streamlit as st
import psycopg2.extras
import pandas as pd
import hashlib
import io
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
from utils.db_pool import get_connection

st.set_page_config(page_title="Sincronização do DW", page_icon="🔄", layout="wide")

# ==============================================================================
# FUNÇÕES DE BANCO DE DADOS (via pool compartilhado)
# ==============================================================================
def obter_ultima_sincronizacao(modulo):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT data_fim_coleta FROM sys_controle_sync
                WHERE modulo = %s AND status = 'SUCESSO'
                ORDER BY data_fim_coleta DESC LIMIT 1;
            """, (modulo,))
            resultado = cur.fetchone()
    return resultado[0] if resultado else None


def registrar_sincronizacao(modulo, data_inicio, data_fim, status, registros):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO sys_controle_sync (modulo, data_inicio_coleta, data_fim_coleta, status, registros_afetados)
                VALUES (%s, %s, %s, %s, %s);
            """, (modulo, data_inicio, data_fim, status, registros))


def fatiar_periodo(start_date, end_date, max_dias=14):
    blocos = []
    atual = start_date
    while atual < end_date:
        proximo = min(atual + timedelta(days=max_dias), end_date)
        blocos.append((atual, proximo))
        atual = proximo
    return blocos


# ==============================================================================
# IDEMPOTÊNCIA POR ARQUIVO (sys_lotes_importacao — migração 12)
# As funções são tolerantes: sem a migração 12, apenas desligam a proteção.
# ==============================================================================
def calcular_hash_arquivo(uploaded_file) -> str:
    return hashlib.sha256(uploaded_file.getvalue()).hexdigest()


def lote_ja_importado(modulo, hash_arquivo, periodo_inicio, periodo_fim):
    """Retorna quando este exato arquivo+período já foi gravado, ou None."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT criado_em FROM sys_lotes_importacao
                    WHERE modulo = %s AND hash_arquivo = %s
                      AND periodo_inicio = %s AND periodo_fim = %s
                    ORDER BY criado_em DESC LIMIT 1;
                """, (modulo, hash_arquivo, periodo_inicio, periodo_fim))
                resultado = cur.fetchone()
        return resultado[0] if resultado else None
    except Exception as e:
        logger.warning(f"Registro de lotes indisponível (migração 12 pendente?): {e}")
        return None


def registrar_lote_importacao(modulo, nome_arquivo, hash_arquivo, periodo_inicio, periodo_fim, registros):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO sys_lotes_importacao
                        (modulo, nome_arquivo, hash_arquivo, periodo_inicio, periodo_fim, registros_gravados)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (modulo, hash_arquivo, periodo_inicio, periodo_fim) DO UPDATE SET
                        registros_gravados = EXCLUDED.registros_gravados,
                        criado_em = CURRENT_TIMESTAMP;
                """, (modulo, nome_arquivo[:255], hash_arquivo, periodo_inicio, periodo_fim, registros))
    except Exception as e:
        logger.warning(f"Não foi possível registrar o lote de importação: {e}")


def buscar_importacoes_sobrepostas(modulo, periodo_inicio, periodo_fim):
    """Lotes antigos com período DIFERENTE que cruzam o novo: o rateio diverge."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT nome_arquivo, periodo_inicio, periodo_fim
                    FROM sys_lotes_importacao
                    WHERE modulo = %s
                      AND periodo_inicio <= %s AND periodo_fim >= %s
                      AND NOT (periodo_inicio = %s AND periodo_fim = %s)
                    ORDER BY criado_em DESC LIMIT 5;
                """, (modulo, periodo_fim, periodo_inicio, periodo_inicio, periodo_fim))
                return cur.fetchall()
    except Exception:
        return []


# ==============================================================================
# PROCESSADOR INTELIGENTE (Bypass de Arquivos da Shopee)
# ==============================================================================
def limpar_valor(val):
    """Converte texto monetário/percentual em float, detectando formato BR e EN.

    Regras: vírgula presente → formato BR (ponto é milhar). Só pontos e mais de
    um → todos são milhar. Um único ponto seguido de exatamente 3 dígitos →
    milhar BR ("1.234" = 1234); caso contrário é decimal ("12.5" = 12.5).
    """
    if pd.isna(val) or val == '-':
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace('R$', '').replace('%', '').strip().replace(' ', '')
    if not s:
        return 0.0
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    elif s.count('.') > 1:
        s = s.replace('.', '')
    elif s.count('.') == 1 and re.fullmatch(r'-?\d{1,3}(\.\d{3})', s):
        s = s.replace('.', '')
    try:
        return float(s)
    except ValueError:
        return 0.0


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


def granularidade_do_periodo(dias_no_periodo: int) -> str:
    """Uploads de 1 dia são observações reais; períodos maiores são rateados."""
    return "DIARIA" if dias_no_periodo == 1 else "AGREGADA_PERIODO"


def carregar_dataframe_limpo(uploaded_file):
    """Filtro inteligente para pular o cabeçalho 'sujo' e avisos da Shopee"""
    if uploaded_file.name.endswith('.csv'):
        texto = uploaded_file.getvalue().decode('utf-8-sig')
        linhas = texto.splitlines()
        idx_cabecalho = 0
        for i, linha in enumerate(linhas[:20]):
            linha_low = linha.lower()
            # 'nome do produto' garante a leitura do arquivo GMV Max Detail
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


# ==============================================================================
# PROCESSADOR: VISÃO GERAL DA LOJA (métricas macro, datas reais por linha)
# ==============================================================================
def processar_arquivo_global(arquivo_global):
    if not arquivo_global:
        return 0, "Nenhum arquivo de visão geral recebido.", None, None

    try:
        df = carregar_dataframe_limpo(arquivo_global)
        if df.empty:
            return 0, "Arquivo vazio ou sem conteúdo reconhecido.", None, None

        col_data = next((c for c in df.columns if any(k in c.lower() for k in ['data', 'date', 'dia', 'periodo', 'period'])), None)
        if not col_data:
            return 0, "Não foi possível identificar uma coluna de data no arquivo.", None, None

        metricas = []
        for col in df.columns:
            if col == col_data:
                continue
            nome_col = col.lower()
            if not any(k in nome_col for k in ['venda', 'receita', 'gmv', 'lucro', 'margem', 'custo', 'ads', 'visita', 'conversao', 'rejei', 'cancel', 'pedido', 'estoque', 'preco', 'price', 'roas', 'taxa']):
                continue

            nome_metric = normalizar_nome_metric(col)
            for _, row in df.iterrows():
                try:
                    data_val = pd.to_datetime(row[col_data], errors='coerce', dayfirst=True)
                    if pd.isna(data_val):
                        continue
                except Exception:
                    continue

                valor = limpar_valor(row[col]) if pd.notna(row[col]) and str(row[col]).strip() not in {'-', ''} else 0.0
                metricas.append((data_val.date(), nome_metric, float(valor), arquivo_global.name))

        if not metricas:
            return 0, "Não foram encontradas métricas reconhecíveis para armazenar.", None, None

        with get_connection() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, """
                    INSERT INTO fato_visao_geral_loja (data_registro, metric_name, metric_value, fonte)
                    VALUES %s
                    ON CONFLICT (data_registro, metric_name, fonte) DO UPDATE SET
                        metric_value = EXCLUDED.metric_value;
                """, metricas)

        datas = [m[0] for m in metricas]
        return len(metricas), "Sucesso", min(datas), max(datas)
    except Exception as e:
        return 0, f"Erro ao processar arquivo global: {e}", None, None


# ==============================================================================
# PROCESSADOR: TRÁFEGO ORGÂNICO (Performance do Produto)
# ==============================================================================
def processar_trafego_organico(arquivo_trafego, data_inicio, data_fim):
    dias_no_periodo = (data_fim - data_inicio).days + 1
    if dias_no_periodo <= 0:
        return 0, "A Data Final deve ser maior ou igual à Inicial."

    if not arquivo_trafego:
        return 0, "Nenhum arquivo de tráfego fornecido."

    granularidade = granularidade_do_periodo(dias_no_periodo)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT item_id FROM dim_produtos")
            ids_validos = {row[0] for row in cur.fetchall()}

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
                try:
                    item_id = int(limpar_valor(row[col_id]))
                except Exception:
                    continue
            else:
                continue

            if item_id not in ids_validos:
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
                if any(k in col.lower() for k in ['venda', 'receita', 'gmv', 'pedido', 'ticket', 'avg', 'reemb', 'cancel', 'devol', 'margem', 'custo', 'gasto', 'ads', 'despesa', 'cpc', 'ctr', 'conversao', 'preco', 'price', 'stock', 'estoque', 'roas', 'taxa']):
                    valor = limpar_valor(row[col]) if pd.notna(row[col]) and str(row[col]).strip() not in {'-', ''} else 0.0
                    if valor == 0:
                        continue
                    for d in range(dias_no_periodo):
                        dia_registro = data_inicio + timedelta(days=d)
                        add_metrica(item_id, dia_registro.date(), normalizar_nome_metric(col), valor / dias_no_periodo, arquivo_trafego.name)

    except Exception as e:
        return 0, f"Erro ao ler Tráfego Orgânico: {e}"

    linhas_trafego = [
        (k[0], k[1], v[0], v[1], v[2], round(v[3] / v[5], 2), v[4], granularidade)
        for k, v in dict_trafego.items()
    ]

    metricas_importadas = [
        (chave[0], chave[1], chave[2], valor, chave[3])
        for chave, valor in dict_metricas.items()
    ]

    if linhas_trafego or metricas_importadas:
        with get_connection() as conn:
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

    return len(linhas_trafego), "Sucesso"


# ==============================================================================
# PROCESSADOR: SHOPEE ADS AVANÇADO (GMV Max + Padrão, múltiplos arquivos)
# ==============================================================================
def processar_relatorio_ads_avancado(arquivos_ads, data_inicio, data_fim):
    if not arquivos_ads:
        return 0, "Nenhum arquivo de Ads fornecido."

    if not isinstance(arquivos_ads, list):
        arquivos_ads = [arquivos_ads]

    dias_no_periodo = (data_fim - data_inicio).days + 1
    if dias_no_periodo <= 0:
        return 0, "Data inválida."

    granularidade = granularidade_do_periodo(dias_no_periodo)

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Garante que o item 0 existe na dimensão para aceitar gastos da Loja
            cur.execute("""
                INSERT INTO dim_produtos (item_id, nome_atual, status_shopee)
                VALUES (0, 'LOJA GLOBAL (ADS DA LOJA)', 'NORMAL')
                ON CONFLICT (item_id) DO NOTHING;
            """)
            cur.execute("SELECT item_id, LOWER(nome_atual) FROM dim_produtos")
            produtos_db = cur.fetchall()

    ids_validos = {pid for pid, _ in produtos_db}

    # Acumula por (item_id, tipo_campanha) ANTES do rateio: várias campanhas
    # PADRAO do mesmo produto viram uma linha por dia (a PK do fato exige isso;
    # duas linhas iguais no mesmo INSERT causariam erro do ON CONFLICT).
    def _somar_opcional(atual, novo):
        if novo is None:
            return atual
        return (atual or 0) + novo

    agregados = {}  # (item_id, tipo_campanha) -> métricas somadas do período

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

            # É um arquivo de detalhes do GMV Max? (Se sim, todos os itens são GMV_MAX)
            is_detail_file = 'gmv max' in arquivo_ads.name.lower()

            for _, row in df.iterrows():
                item_id = None
                nome_anuncio_raw = str(row.get(col_nome, "")) if col_nome else ""
                nome_csv_lower = nome_anuncio_raw.lower().strip()

                # IDENTIFICAÇÃO DO GMV MAX
                is_gmv_max = is_detail_file
                if not is_gmv_max and col_metodo_lance and pd.notna(row.get(col_metodo_lance)):
                    if 'gmv max' in str(row[col_metodo_lance]).lower():
                        is_gmv_max = True

                if not is_gmv_max:
                    for valor_celula in row.dropna():
                        if 'gmv max' in str(valor_celula).lower():
                            is_gmv_max = True
                            break

                # ALOCAÇÃO DE IDs E PREVENÇÃO DE DUPLA CONTAGEM
                is_shop_level = False
                if col_id and str(row.get(col_id, '')).strip() == '-':
                    is_shop_level = True

                    if is_gmv_max:
                        # Linha-total do GMV Max no arquivo "Dados Gerais": os valores
                        # virão diluídos por SKU no arquivo "Detalhes GMV Max".
                        continue
                    else:
                        # Campanha de Busca da Loja (tradicional): salva na entidade Loja.
                        item_id = 0

                if not is_shop_level and col_id and pd.notna(row.get(col_id)) and str(row.get(col_id, '')).strip() != '-':
                    try:
                        item_id = int(limpar_valor(row.get(col_id)))
                    except Exception:
                        pass

                # Fallback: ligar pelo nome do anúncio ao nome do produto na base
                if not item_id and not is_shop_level and col_nome:
                    for pid, pnome in produtos_db:
                        if pnome and (pnome in nome_csv_lower or nome_csv_lower in pnome):
                            item_id = pid
                            break

                if item_id is None:
                    continue

                # Item de campanha que não existe na dimensão: vira gasto da Loja
                # em vez de quebrar a FK (produto excluído da Shopee, por exemplo).
                if item_id not in ids_validos:
                    logger.warning(f"Ads para item {item_id} sem cadastro na dim_produtos; alocado na Loja Global.")
                    item_id = 0

                tipo_campanha = 'GMV_MAX' if is_gmv_max else 'PADRAO'

                imp_raw = limpar_valor_opcional(row.get(col_imp)) if col_imp else None
                cli_raw = limpar_valor_opcional(row.get(col_cli)) if col_cli else None
                imp = int(imp_raw) if imp_raw is not None else None
                cli = int(cli_raw) if cli_raw is not None else None
                inv = limpar_valor(row.get(col_inv)) if col_inv else 0.0
                gmv = limpar_valor(row.get(col_gmv)) if col_gmv else 0.0
                cart = int(limpar_valor(row.get(col_cart))) if col_cart else 0
                conv = int(limpar_valor(row.get(col_conv))) if col_conv else 0
                itens = int(limpar_valor(row.get(col_itens))) if col_itens else 0

                # Impede a inserção inútil de linhas vazias
                if inv == 0 and gmv == 0 and imp in (0, None) and cli in (0, None):
                    continue

                chave = (item_id, tipo_campanha)
                if chave not in agregados:
                    agregados[chave] = {
                        "nome": nome_anuncio_raw, "imp": imp, "cli": cli,
                        "inv": inv, "gmv": gmv, "cart": cart, "conv": conv, "itens": itens,
                        "campanhas": 1,
                    }
                else:
                    m = agregados[chave]
                    m["imp"] = _somar_opcional(m["imp"], imp)
                    m["cli"] = _somar_opcional(m["cli"], cli)
                    m["inv"] += inv
                    m["gmv"] += gmv
                    m["cart"] += cart
                    m["conv"] += conv
                    m["itens"] += itens
                    m["campanhas"] += 1
                    if nome_anuncio_raw and nome_anuncio_raw not in m["nome"]:
                        m["nome"] = f"{m['nome']} + {nome_anuncio_raw}"

        except Exception as e:
            logger.error(f"Erro ao processar um dos arquivos de Ads ({arquivo_ads.name}): {e}")
            continue

    if not agregados:
        return 0, "Nenhum dado válido extraído dos arquivos."

    # Rateio temporal por chave agregada. ROAS/ACOS são recalculados dos totais
    # (média das linhas do arquivo distorceria campanhas de pesos diferentes).
    linhas_insercao = []
    for (item_id, tipo_campanha), m in agregados.items():
        roas = round(m["gmv"] / m["inv"], 2) if m["inv"] > 0 else 0.0
        acos = round(m["inv"] / m["gmv"] * 100, 2) if m["gmv"] > 0 else 0.0
        nome_final = (m["nome"] or "")[:250]
        for d in range(dias_no_periodo):
            dia_registro = data_inicio + timedelta(days=d)
            linhas_insercao.append((
                item_id, dia_registro.date(), tipo_campanha, nome_final,
                distribuir_inteiro(m["imp"], dias_no_periodo, d),
                distribuir_inteiro(m["cli"], dias_no_periodo, d),
                distribuir_monetario(m["inv"], dias_no_periodo, d),
                distribuir_monetario(m["gmv"], dias_no_periodo, d),
                distribuir_inteiro(m["cart"], dias_no_periodo, d),
                distribuir_inteiro(m["conv"], dias_no_periodo, d),
                distribuir_inteiro(m["itens"], dias_no_periodo, d),
                roas, acos, granularidade,
            ))

    try:
        with get_connection() as conn:
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

# Exibe o status atual do banco
col_a, col_b, col_c, col_d = st.columns(4)
ultima_sync_pedidos = obter_ultima_sincronizacao('PEDIDOS')
ultima_sync_org = obter_ultima_sincronizacao('TRAFEGO_ORG')
ultima_sync_ads = obter_ultima_sincronizacao('ADS_AVANCADO')
ultima_sync_global = obter_ultima_sincronizacao('VISAO_GERAL')

with col_a: st.info(f"📦 Pedidos (API): **{ultima_sync_pedidos.strftime('%d/%m %H:%M') if ultima_sync_pedidos else 'Nunca'}**")
with col_b: st.info(f"🌿 Tráfego Orgânico: **{ultima_sync_org.strftime('%d/%m/%Y') if ultima_sync_org else 'Nunca'}**")
with col_c: st.info(f"🎯 Shopee Ads: **{ultima_sync_ads.strftime('%d/%m/%Y') if ultima_sync_ads else 'Nunca'}**")
with col_d: st.info(f"📈 Visão Geral: **{ultima_sync_global.strftime('%d/%m/%Y') if ultima_sync_global else 'Nunca'}**")

st.divider()

st.caption(
    "💡 **Dica de qualidade de dado:** exportações de **1 dia** são gravadas como observação DIÁRIA real; "
    "períodos maiores são rateados (AGREGADA_PERIODO). Quanto mais dias diários o banco tiver, "
    "mais precisa (e mais barata) fica a análise do Cérebro IA — a cobertura diária melhora a "
    "classificação de evidência e aumenta o reaproveitamento do cache semântico."
)

aba_principal, aba_ads, aba_global = st.tabs([
    "⚙️ Operação & Orgânico (API)",
    "📢 Shopee Ads Avançado",
    "📈 Visão Geral da Loja"
])

# ------------------------------------------------------------------------------
# ABA 1 — OPERAÇÃO & ORGÂNICO
# ------------------------------------------------------------------------------
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

    # Proteções pré-processamento: arquivo repetido e períodos sobrepostos
    processar_trafego_permitido = True
    if arquivo_trafego and datas_validas:
        hash_trafego = calcular_hash_arquivo(arquivo_trafego)
        importado_em = lote_ja_importado('TRAFEGO_ORG', hash_trafego, periodo_selecionado[0], periodo_selecionado[1])
        if importado_em:
            st.warning(f"⚠️ Este exato arquivo já foi importado em **{importado_em.strftime('%d/%m/%Y %H:%M')}** com o mesmo período. Reimportar não muda nada no banco.")
            processar_trafego_permitido = st.checkbox("Reimportar mesmo assim", key="forcar_trafego")
        sobrepostos = buscar_importacoes_sobrepostas('TRAFEGO_ORG', periodo_selecionado[0], periodo_selecionado[1])
        if sobrepostos:
            detalhes = "; ".join(f"{n} ({pi:%d/%m} a {pf:%d/%m})" for n, pi, pf in sobrepostos)
            st.warning(
                f"⚠️ O período escolhido cruza importações anteriores com período diferente: {detalhes}. "
                "O rateio diário dos dias em comum será sobrescrito pelo novo arquivo — prefira períodos consistentes (ex.: sempre semanas fechadas ou sempre 1 dia)."
            )

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
                ultimo_fim_ok = None

                for i, (inicio_bloco, fim_bloco) in enumerate(blocos):
                    res_ped = sincronizar_pedidos(inicio_bloco, fim_bloco)
                    if res_ped["status"] == "sucesso":
                        total_pedidos += res_ped["registros"]
                        ultimo_fim_ok = fim_bloco
                    else:
                        st.error(
                            f"Erro na API de Pedidos no bloco {inicio_bloco:%d/%m} a {fim_bloco:%d/%m}. "
                            "O avanço até o último bloco concluído foi preservado — rode novamente para continuar de onde parou."
                        )
                        break
                    barra.progress((i + 1) / len(blocos))

                # Persiste o avanço mesmo com interrupção no meio: a próxima
                # sincronização retoma do último bloco concluído (margem de 4
                # dias), em vez de repetir todo o período do zero.
                if ultimo_fim_ok:
                    registrar_sincronizacao('PEDIDOS', ultima_sync_pedidos or dt_inicio_pedidos, ultimo_fim_ok, 'SUCESSO', total_pedidos)

                sync_completo = bool(blocos) and ultimo_fim_ok == blocos[-1][1]
                if sync_completo:
                    status.update(label=f"Motor Financeiro atualizado! ({total_pedidos} pedidos consolidados)", state="complete")
                else:
                    status.update(label=f"Sincronização de pedidos parcial ({total_pedidos} pedidos salvos). Rode novamente para completar.", state="error")

        if arquivo_trafego and not processar_trafego_permitido:
            st.info("📄 Planilha de tráfego ignorada: arquivo idêntico já importado (marque 'Reimportar mesmo assim' para forçar).")
        elif arquivo_trafego:
            with st.status(f"3. Processando Tráfego Orgânico ({dt_inicio_csv.strftime('%d/%m')} a {dt_fim_csv.strftime('%d/%m')})...", expanded=True) as status:
                linhas, msg = processar_trafego_organico(arquivo_trafego, dt_inicio_csv, dt_fim_csv)

                if msg == "Sucesso":
                    registrar_sincronizacao('TRAFEGO_ORG', dt_inicio_csv, dt_fim_csv, 'SUCESSO', linhas)
                    registrar_lote_importacao('TRAFEGO_ORG', arquivo_trafego.name, calcular_hash_arquivo(arquivo_trafego),
                                              periodo_selecionado[0], periodo_selecionado[1], linhas)
                    granular = granularidade_do_periodo((dt_fim_csv.date() - dt_inicio_csv.date()).days + 1)
                    status.update(label=f"Tráfego Consolidado! ({linhas} registros, granularidade {granular})", state="complete")
                else:
                    status.update(label=f"Falha no CSV: {msg}", state="error"); st.stop()

        st.balloons()
        st.success("🎉 Sincronização API finalizada! Sua base operacional e financeira está atualizada.")

# ------------------------------------------------------------------------------
# ABA 2 — SHOPEE ADS AVANÇADO
# ------------------------------------------------------------------------------
with aba_ads:
    st.markdown("### 🎯 Inteligência de Shopee Ads (GMV Max & Padrão)")
    st.markdown("""
    Esta sessão alimenta o Data Warehouse com dados de campanhas pagas. Aceita **múltiplos arquivos simultaneamente**.
    O sistema extrairá os custos totais da loja (GMV Max Global) e os detalhes de cada produto.
    """)

    st.info("🛡️ **Idempotente:** Pode enviar arquivos do mês todo sem medo de duplicação de gastos. Arquivos repetidos são detectados pelo conteúdo.")

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
        arquivos_ads_avancado = st.file_uploader("📂 2. Arraste todos os arquivos de Ads aqui", type=["csv", "xlsx"], key="upload_ads_avancado", accept_multiple_files=True)

    datas_ads_validas = isinstance(periodo_ads, tuple) and len(periodo_ads) == 2

    # Proteções pré-processamento: arquivos repetidos e períodos sobrepostos
    arquivos_ads_novos = list(arquivos_ads_avancado or [])
    if arquivos_ads_avancado and datas_ads_validas:
        repetidos = []
        for arq in arquivos_ads_avancado:
            importado_em = lote_ja_importado('ADS_AVANCADO', calcular_hash_arquivo(arq), periodo_ads[0], periodo_ads[1])
            if importado_em:
                repetidos.append((arq.name, importado_em))
        if repetidos:
            nomes = ", ".join(f"**{n}** ({d.strftime('%d/%m %H:%M')})" for n, d in repetidos)
            st.warning(f"⚠️ Arquivo(s) já importado(s) com este mesmo período: {nomes}.")
            if not st.checkbox("Reimportar arquivos repetidos mesmo assim", key="forcar_ads"):
                nomes_repetidos = {n for n, _ in repetidos}
                arquivos_ads_novos = [a for a in arquivos_ads_avancado if a.name not in nomes_repetidos]

        sobrepostos_ads = buscar_importacoes_sobrepostas('ADS_AVANCADO', periodo_ads[0], periodo_ads[1])
        if sobrepostos_ads:
            detalhes = "; ".join(f"{n} ({pi:%d/%m} a {pf:%d/%m})" for n, pi, pf in sobrepostos_ads)
            st.warning(
                f"⚠️ O período escolhido cruza importações de Ads com período diferente: {detalhes}. "
                "Os dias em comum serão sobrescritos com o novo rateio; dias fora do novo período mantêm o rateio antigo."
            )

    if st.button("🧠 PROCESSAR INTELIGÊNCIA DE ADS", type="primary", use_container_width=True, disabled=not arquivos_ads_novos or not datas_ads_validas):
        dt_inicio_ads = datetime.combine(periodo_ads[0], datetime.min.time())
        dt_fim_ads = datetime.combine(periodo_ads[1], datetime.max.time())

        with st.status(f"Mapeando campanhas de {len(arquivos_ads_novos)} arquivo(s)... ({dt_inicio_ads.strftime('%d/%m')} a {dt_fim_ads.strftime('%d/%m')})", expanded=True) as status_ads:
            linhas_ads, msg_ads = processar_relatorio_ads_avancado(arquivos_ads_novos, dt_inicio_ads, dt_fim_ads)

            if msg_ads == "Sucesso":
                registrar_sincronizacao('ADS_AVANCADO', dt_inicio_ads, dt_fim_ads, 'SUCESSO', linhas_ads)
                for arq in arquivos_ads_novos:
                    registrar_lote_importacao('ADS_AVANCADO', arq.name, calcular_hash_arquivo(arq),
                                              periodo_ads[0], periodo_ads[1], linhas_ads)
                status_ads.update(label=f"Análise Concluída! Foram injetados {linhas_ads} dias-registro de inteligência.", state="complete")
                st.balloons()
            else:
                status_ads.update(label=f"Aviso de leitura: {msg_ads}", state="error")

# ------------------------------------------------------------------------------
# ABA 3 — VISÃO GERAL DA LOJA
# ------------------------------------------------------------------------------
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

    processar_global_permitido = True
    if arquivo_global:
        # A visão geral tem datas reais por linha, então o hash sozinho basta
        # para detectar reimportação (o período só é conhecido após o parse).
        hash_global = calcular_hash_arquivo(arquivo_global)
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT criado_em FROM sys_lotes_importacao
                        WHERE modulo = 'VISAO_GERAL' AND hash_arquivo = %s
                        ORDER BY criado_em DESC LIMIT 1;
                    """, (hash_global,))
                    r = cur.fetchone()
                    importado_em = r[0] if r else None
        except Exception:
            importado_em = None
        if importado_em:
            st.warning(f"⚠️ Este exato arquivo já foi importado em **{importado_em.strftime('%d/%m/%Y %H:%M')}**.")
            processar_global_permitido = st.checkbox("Reimportar mesmo assim", key="forcar_global")

    if arquivo_global and processar_global_permitido:
        if st.button("🚀 PROCESSAR VISÃO GERAL DA LOJA", type="primary", use_container_width=True):
            with st.status("Consolidando métricas globais e alimentando o DW...", expanded=True) as status_global:
                linhas_global, msg_global, data_min, data_max = processar_arquivo_global(arquivo_global)

                if msg_global == "Sucesso":
                    registrar_sincronizacao('VISAO_GERAL',
                                            datetime.combine(data_min, datetime.min.time()),
                                            datetime.combine(data_max, datetime.max.time()),
                                            'SUCESSO', linhas_global)
                    registrar_lote_importacao('VISAO_GERAL', arquivo_global.name, calcular_hash_arquivo(arquivo_global),
                                              data_min, data_max, linhas_global)
                    status_global.update(label=f"Visão geral importada com sucesso! ({linhas_global} métricas de {data_min:%d/%m} a {data_max:%d/%m})", state="complete")
                    st.balloons()
                else:
                    status_global.update(label=f"Falha na importação da visão geral: {msg_global}", state="error")
