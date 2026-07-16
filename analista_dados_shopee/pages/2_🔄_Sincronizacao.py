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

import streamlit as st
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
from utils.db_pool import get_connection

st.set_page_config(page_title="Sincronização do DW", page_icon="🔄", layout="wide")

from utils.ui import aplicar_estilo, cabecalho, nota
aplicar_estilo()

# Processadores de planilhas e controle de sync — extraídos para
# workers/importar_planilhas.py (testáveis fora do Streamlit e corrigidos
# contra exports reais de Ads; ver docstring do módulo).
from workers.importar_planilhas import (
    buscar_importacoes_sobrepostas,
    calcular_hash_arquivo,
    fatiar_periodo,
    granularidade_do_periodo,
    lote_ja_importado,
    obter_ultima_sincronizacao,
    processar_arquivo_global,
    processar_relatorio_ads_avancado,
    processar_trafego_organico,
    registrar_lote_importacao,
    registrar_sincronizacao,
)

# ==============================================================================
# INTERFACE COM ABAS (TABS) E LINKS RÁPIDOS
# ==============================================================================
cabecalho("🔄", "Sincronização e Data Warehouse",
           "API oficial + planilhas do Seller Center (CSV/XLSX) — tudo processado de forma consistente para alimentar o Cérebro.")

# Última atualização de cada fonte de dado (cartões de métrica do design system)
ultima_sync_pedidos = obter_ultima_sincronizacao('PEDIDOS')
ultima_sync_org = obter_ultima_sincronizacao('TRAFEGO_ORG')
ultima_sync_ads = obter_ultima_sincronizacao('ADS_AVANCADO')
ultima_sync_global = obter_ultima_sincronizacao('VISAO_GERAL')

col_a, col_b, col_c, col_d = st.columns(4)
col_a.metric("📦 Pedidos (API)", ultima_sync_pedidos.strftime('%d/%m %H:%M') if ultima_sync_pedidos else "Nunca")
col_b.metric("🌿 Tráfego Orgânico", ultima_sync_org.strftime('%d/%m/%Y') if ultima_sync_org else "Nunca")
col_c.metric("🎯 Shopee Ads", ultima_sync_ads.strftime('%d/%m/%Y') if ultima_sync_ads else "Nunca")
col_d.metric("📈 Visão Geral", ultima_sync_global.strftime('%d/%m/%Y') if ultima_sync_global else "Nunca")

st.markdown("")
nota(
    "Exportações de <b>1 dia</b> são gravadas como observação DIÁRIA real; períodos maiores são "
    "rateados (AGREGADA_PERIODO). Quanto mais dias diários o banco tiver, mais precisa (e mais "
    "barata) fica a análise do Cérebro IA.",
    titulo="Dica de qualidade de dado",
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
    st.markdown(
        "Sincroniza os **pedidos pela API** e importa a planilha de **Performance do Produto** "
        "(visitas, adições ao carrinho e taxa de rejeição) para medir a saúde orgânica da loja."
    )
    st.caption("🛡️ Reenviar planilhas com datas repetidas é seguro: o sistema apenas atualiza os registros existentes.")

    hoje = datetime.now()
    data_sugerida_inicio = ultima_sync_org if ultima_sync_org else (hoje - timedelta(days=30))

    periodo_selecionado = st.date_input("📅 1. Qual período você selecionou ao exportar a planilha na Shopee?",
                                        value=(data_sugerida_inicio.date(), hoje.date()),
                                        max_value=hoje.date())

    with st.expander("📥 Como exportar a planilha de Performance correta (passo a passo)"):
        st.markdown("""
        1. Acesse o painel pelo botão abaixo. Ele abrirá diretamente a aba **Informações Gerenciais > Produto > Performance do Produto**.
        2. No filtro de calendário (Período dos Dados) no topo, selecione o mesmo período que você escolheu acima.
        3. Na seção "Desempenho do Produto" (lista com os itens), clique no botão azul **Exportar**.
        4. Suba o arquivo Excel/CSV gerado aqui.
        """)
        st.link_button("🔗 Abrir Business Insights > Desempenho do Produto", "https://seller.shopee.com.br/datacenter/product/performance", use_container_width=True)

    arquivo_trafego = st.file_uploader("📂 2. Arraste o arquivo de Performance do Produto aqui", type=["csv", "xlsx"], key="upload_trafego")

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

    if st.button("🚀 3. Iniciar sincronização completa (API + planilha)", type="primary", use_container_width=True, disabled=not datas_validas):

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
    st.markdown(
        "Alimenta o Data Warehouse com as campanhas pagas — custos totais da loja (GMV Max Global) "
        "e detalhes por produto. Aceita **vários arquivos de uma vez**."
    )
    st.caption("🛡️ Pode enviar arquivos do mês todo sem medo de duplicar gastos: repetidos são detectados pelo conteúdo.")

    with st.expander("📥 Passo a passo para a exportação perfeita"):
        st.markdown("""
        1. Abra a **Central de Marketing** > **Shopee Ads**.
        2. Role a página até encontrar a tabela **Todos os Anúncios de Produtos**.
        3. Defina o calendário e ative TODAS as métricas em "Diagnóstico".
        4. Clique em Exportar e baixe o arquivo **"Dados Gerais de Anúncios"**.
        5. Se você roda GMV MAX, exporte também o **"Dados do GMV MAX"** na mesma página.
        6. **Arraste todos os arquivos baixados de uma só vez na caixa ao lado.**
        """)
        st.link_button("🔗 Abrir Painel do Shopee Ads", "https://seller.shopee.com.br/portal/marketing/pas/index", use_container_width=True)

    col_data_ads, col_upload_ads = st.columns([1, 2])
    with col_data_ads:
        hoje = datetime.now()
        data_sugerida_ads = ultima_sync_ads if ultima_sync_ads else (hoje - timedelta(days=7))
        periodo_ads = st.date_input("📅 1. Período selecionado no Shopee Ads",
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

    if st.button("🧠 3. Processar inteligência de Ads", type="primary", use_container_width=True, disabled=not arquivos_ads_novos or not datas_ads_validas):
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
    st.markdown("Captura as métricas totais da loja para comparar o faturamento geral com os custos e o tráfego total.")
    st.caption("🛡️ Se subir os mesmos dias de novo, o Data Warehouse apenas sobrescreve com os dados mais consolidados.")

    with st.expander("📥 Como extrair a Visão Geral (passo a passo)"):
        st.markdown("""
        1. Entre em **Informações Gerenciais** usando o botão abaixo.
        2. No menu lateral, clique em **Painel**.
        3. Logo abaixo das abas, garanta que você está na aba primária chamada **Visão Geral** (Overview).
        4. Selecione o período no calendário e clique em **Exportar**.
        """)
        st.link_button("🔗 Abrir Painel de Visão Geral", "https://seller.shopee.com.br/datacenter/dashboard", use_container_width=True)

    arquivo_global = st.file_uploader("📂 1. Arraste a planilha de Visão Geral exportada", type=["csv", "xlsx"], key="upload_global")

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
        if st.button("🚀 2. Processar Visão Geral da loja", type="primary", use_container_width=True):
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
