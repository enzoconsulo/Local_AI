"""
workers/importar_planilhas.py
=============================
Processadores das planilhas exportadas do Seller Center (Performance do
Produto, Shopee Ads, Visão Geral da Loja) e helpers de controle de sync.

Extraído da página 2 para ser testável e reutilizável fora do Streamlit —
as funções aceitam qualquer objeto com .name e .getvalue() (UploadedFile do
Streamlit ou ArquivoLocal abaixo, para CLI/testes).

Correções validadas contra exports REAIS de jul/2026:
  1. Coluna de investimento: o export real traz "Custo por Conversão" ANTES de
     "Despesas"; a detecção antiga por substring 'custo' capturava a coluna
     errada e gravava custo-por-conversão como gasto (distorcia ROAS/ACOS).
  2. Detecção do arquivo GMV Max Detail: o download real chama-se
     "Shop+GMV+MAX-Detail-..." (com '+'); a busca por 'gmv max' com espaço
     falhava e os produtos do GMV Max viravam campanha PADRAO.
  3. Arquivo "Ad Group" é recusado com aviso: grupos de anúncio são
     subdivisões das campanhas do "Dados Gerais" — importar os dois somaria o
     mesmo gasto duas vezes.
  4. "Add to Cart" (inglês) reconhecido como adições ao carrinho.
  5. limpar_valor entende milhar EN ("1,234.56").
"""

import hashlib
import io
import re
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd
import psycopg2.extras
from loguru import logger

from utils.db_pool import get_connection


class ArquivoLocal:
    """Adapta um arquivo em disco à interface do UploadedFile do Streamlit."""

    def __init__(self, caminho):
        self._caminho = Path(caminho)
        self.name = self._caminho.name
        self._conteudo = None

    def getvalue(self) -> bytes:
        if self._conteudo is None:
            self._conteudo = self._caminho.read_bytes()
        return self._conteudo


# ==============================================================================
# CONTROLE DE SINCRONIZAÇÃO E LOTES (sys_controle_sync / sys_lotes_importacao)
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
# LIMPEZA E RATEIO DE VALORES
# ==============================================================================

def limpar_valor(val):
    """Converte texto monetário/percentual em float, detectando formato BR e EN.

    Regras: "1,234.56" (milhar EN) → 1234.56. Vírgula sem esse padrão → formato
    BR (ponto é milhar). Só pontos e mais de um → todos são milhar. Um único
    ponto seguido de exatamente 3 dígitos → milhar BR ("1.234" = 1234); caso
    contrário é decimal ("12.5" = 12.5).
    """
    if pd.isna(val) or val == '-':
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace('R$', '').replace('%', '').strip().replace(' ', '')
    if not s:
        return 0.0
    if re.fullmatch(r'-?\d{1,3}(,\d{3})+(\.\d+)?', s):
        s = s.replace(',', '')
    elif ',' in s:
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


def _como_date(valor):
    """Aceita date OU datetime (a página Streamlit passa datetime; CLI/testes
    passam date) e devolve sempre date."""
    return valor.date() if isinstance(valor, datetime) else valor


def carregar_dataframe_limpo(uploaded_file):
    """Filtro inteligente para pular o cabeçalho 'sujo' e avisos da Shopee."""
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
        # Lê dos bytes para honrar o contrato .name/.getvalue() (UploadedFile
        # do Streamlit OU ArquivoLocal); passar o objeto direto ao read_excel
        # só funcionava com o UploadedFile e ainda dependia do seek(0).
        df = pd.read_excel(io.BytesIO(uploaded_file.getvalue()))
        idx_cabecalho = 0
        for i in range(min(15, len(df))):
            valores = str(df.iloc[i].values).lower()
            if 'id do item' in valores or 'id do produto' in valores or 'nome do anúncio' in valores or 'nome do produto' in valores:
                idx_cabecalho = i
                break
        if idx_cabecalho > 0:
            df.columns = df.iloc[idx_cabecalho]
            df = df[idx_cabecalho + 1:].reset_index(drop=True)

    df.columns = df.columns.astype(str).str.lower().str.strip()
    return df


def normalizar_nome_metric(coluna):
    nome = re.sub(r'[^a-z0-9]+', '_', coluna.lower()).strip('_')
    return nome or 'metrica_importada'


def _nome_arquivo_normalizado(nome: str) -> str:
    """Downloads reais vêm com '+' e '%20' no lugar de espaços."""
    return re.sub(r'[+\-_]|%20', ' ', (nome or '').lower())


# ==============================================================================
# PROCESSADOR: VISÃO GERAL DA LOJA (métricas macro, datas reais por linha)
# ==============================================================================

# Colunas não-aditivas (taxas, médias, índices): nunca podem ser somadas entre
# linhas nem rateadas por dia — o valor do período é repetido/médiado.
_METRICAS_DE_TAXA = (
    'taxa', 'rate', 'ctr', 'roas', 'convers', 'rejei', 'perc',
    'medi', 'médi', 'por pedido', 'cpc', 'ticket', 'avg', 'índice', 'indice',
)


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

        # Acumula por (dia, métrica): exports horários (productoverview de 1 dia
        # tem 24 linhas por data) somam contagens e tiram MÉDIA das taxas — o
        # upsert linha a linha antigo guardava só a última hora do dia.
        acumulado = {}  # (date, metric) -> [soma, contagem, é_taxa]
        for col in df.columns:
            if col == col_data:
                continue
            nome_col = col.lower()
            if not any(k in nome_col for k in ['venda', 'receita', 'gmv', 'lucro', 'margem', 'custo', 'ads', 'visita', 'conversao', 'rejei', 'cancel', 'pedido', 'estoque', 'preco', 'price', 'roas', 'taxa', 'clique', 'impress', 'visualiza', 'curtida', 'comprador', 'unidade']):
                continue

            nome_metric = normalizar_nome_metric(col)
            e_taxa = any(k in nome_col for k in _METRICAS_DE_TAXA)
            for _, row in df.iterrows():
                try:
                    data_val = pd.to_datetime(row[col_data], errors='coerce', dayfirst=True)
                    if pd.isna(data_val):
                        continue
                except Exception:
                    continue

                valor = limpar_valor(row[col]) if pd.notna(row[col]) and str(row[col]).strip() not in {'-', ''} else 0.0
                chave = (data_val.date(), nome_metric)
                if chave not in acumulado:
                    acumulado[chave] = [0.0, 0, e_taxa]
                acumulado[chave][0] += float(valor)
                acumulado[chave][1] += 1

        metricas = [
            (data, metric, round(soma / contagem, 4) if e_taxa and contagem else soma, arquivo_global.name)
            for (data, metric), (soma, contagem, e_taxa) in acumulado.items()
        ]

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
    data_inicio, data_fim = _como_date(data_inicio), _como_date(data_fim)
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
        col_id_variacao = next((c for c in df_t.columns if 'id da variação' in c or 'id da variacao' in c), None)
        col_imp_org = next((c for c in df_t.columns if 'impress' in c), None)
        col_cli_org = next((c for c in df_t.columns if 'clique' in c or 'click' in c), None)

        # Meio/Fundo de Funil
        col_visitas = next((c for c in df_t.columns if 'visitante' in c or 'visita' in c), None)
        # No parentskudetail real existem 3 colunas com 'carrinho': "Visitantes
        # do Produto (Adicionar ao Carrinho)", "Unidades (adicionar ao carrinho)"
        # e "Taxa de Conversão (adicionar ao carrinho)". Adições ao carrinho são
        # as UNIDADES adicionadas — visitantes e taxa não podem ser confundidos.
        col_carrinho = (
            next((c for c in df_t.columns if 'carrinho' in c and ('unidade' in c or 'add to cart' in c)), None)
            or next((c for c in df_t.columns if 'carrinho' in c and 'taxa' not in c and 'visitante' not in c), None)
        )
        col_rejeicao = next((c for c in df_t.columns if 'rejeição' in c or 'bounce' in c), None)

        for _, row in df_t.iterrows():
            # O export real (parentskudetail) traz linhas do produto-PAI e de
            # cada variação. Tráfego é medido no anúncio (só o pai tem valor) e
            # as vendas aparecem NOS DOIS níveis: somar tudo dobraria as vendas
            # importadas e diluiria a taxa de rejeição. Só a linha-pai entra.
            if col_id_variacao is not None:
                id_variacao = str(row.get(col_id_variacao, '-')).strip()
                if id_variacao not in {'-', '', 'nan'}:
                    continue

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

                chave_trafego = (item_id, dia_registro)
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
                if any(k in col.lower() for k in ['venda', 'receita', 'gmv', 'pedido', 'pago', 'ticket', 'avg', 'reemb', 'cancel', 'devol', 'margem', 'custo', 'gasto', 'ads', 'despesa', 'cpc', 'ctr', 'conversao', 'preco', 'price', 'stock', 'estoque', 'roas', 'taxa']):
                    valor = limpar_valor(row[col]) if pd.notna(row[col]) and str(row[col]).strip() not in {'-', ''} else 0.0
                    if valor == 0:
                        continue
                    # Taxas/médias (CTR, conversão, vendas por pedido, média de
                    # dias) não são aditivas: ratear por dia produziria números
                    # sem sentido (ex.: conversão de 4,77% virando 0,16%/dia).
                    # O valor do período é repetido em cada dia da janela.
                    e_taxa = any(k in col.lower() for k in _METRICAS_DE_TAXA)
                    for d in range(dias_no_periodo):
                        dia_registro = data_inicio + timedelta(days=d)
                        add_metrica(item_id, dia_registro, normalizar_nome_metric(col), valor if e_taxa else valor / dias_no_periodo, arquivo_trafego.name)

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

def _localizar_coluna_investimento(cols: dict) -> str | None:
    """Prioriza o gasto real ('despesas'/'investimento'); nunca métricas
    derivadas como 'custo por conversão' (bug flagrado em export real)."""
    for exato in ('despesas', 'despesa', 'investimento'):
        if exato in cols:
            return cols[exato]
    for c in cols:
        if ('investimento' in c or 'despesa' in c or 'custo' in c) and 'convers' not in c:
            return cols[c]
    return None


def processar_relatorio_ads_avancado(arquivos_ads, data_inicio, data_fim):
    if not arquivos_ads:
        return 0, "Nenhum arquivo de Ads fornecido."

    if not isinstance(arquivos_ads, list):
        arquivos_ads = [arquivos_ads]

    data_inicio, data_fim = _como_date(data_inicio), _como_date(data_fim)
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
    arquivos_ignorados = []

    for arquivo_ads in arquivos_ads:
        nome_normalizado = _nome_arquivo_normalizado(arquivo_ads.name)

        # Grupos de anúncio são subdivisões das campanhas do "Dados Gerais":
        # importar os dois somaria o mesmo gasto DUAS vezes no DW.
        if 'ad group' in nome_normalizado:
            logger.warning(f"Arquivo de Ad Group ignorado para evitar dupla contagem: {arquivo_ads.name}")
            arquivos_ignorados.append(arquivo_ads.name)
            continue

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
            col_imp = next((cols[c] for c in cols if 'impress' in c and 'produto' not in c), None)
            col_cli = next((cols[c] for c in cols if ('clique' in c or 'click' in c) and 'produto' not in c), None)
            col_inv = _localizar_coluna_investimento(cols)
            col_gmv = next((
                cols[c] for c in cols
                if (('vendas' in c and 'diretas' not in c and 'cupom' not in c) or 'gmv' in c or 'vgm' in c)
            ), None)

            col_cart = next((cols[c] for c in cols if ('carrinho' in c or 'add to cart' in c) and 'taxa' not in c and 'rate' not in c), None)
            col_conv = next((cols[c] for c in cols if ('conversões' in c or 'conversoes' in c) and 'custo' not in c and 'taxa' not in c and 'direta' not in c), None)
            col_itens = next((cols[c] for c in cols if 'itens vendidos' in c and 'direto' not in c), None)

            # É um arquivo de detalhes do GMV Max? Downloads reais usam '+'
            # no lugar de espaço ("Shop+GMV+MAX-Detail-...").
            is_detail_file = 'gmv max' in nome_normalizado

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
        if arquivos_ignorados:
            return 0, (
                "Somente arquivo(s) de Ad Group foram enviados; eles são ignorados para evitar "
                "dupla contagem. Envie o 'Dados Gerais de Anúncios' (e o 'GMV Max Detail', se usar GMV Max)."
            )
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
                item_id, dia_registro, tipo_campanha, nome_final,
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
        mensagem = "Sucesso"
        if arquivos_ignorados:
            mensagem = f"Sucesso ({len(arquivos_ignorados)} arquivo(s) de Ad Group ignorado(s) para evitar dupla contagem)"
        return len(linhas_insercao), mensagem
    except Exception as e:
        return 0, f"Erro crítico de banco de dados na inserção de Ads: {e}"
