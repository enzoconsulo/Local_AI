"""
cerebro/consultor.py
====================
Motor do Assistente de Dados (página 4): text-to-SQL somente leitura sobre o
Data Warehouse + resposta executiva, via API OpenAI direta.

Sem Streamlit: a página injeta um callback de eventos (ao_evento) para exibir
SQL, tabelas e erros; o mesmo motor roda em CLI e testes.

Disciplina de custo por turno de conversa:
  - no máximo 3 chamadas (gerar SQL → 1 reparo opcional → resposta final);
  - histórico enviado = prompt de sistema + últimas 12 mensagens (o prompt de
    sistema NUNCA é cortado — antes ele caía fora após 10 mensagens e o modelo
    esquecia o schema);
  - tabela devolvida ao modelo limitada a 50 linhas e ~3.800 caracteres.
"""

import re
from datetime import datetime

import pandas as pd
import requests
from loguru import logger

from utils.db_pool import get_connection
from cerebro import config

# ══════════════════════════════════════════════════════════════════════════════
# SCHEMA APRESENTADO AO MODELO (atualizado até a migração 14)
# ══════════════════════════════════════════════════════════════════════════════

SCHEMA_DO_BANCO = """
Banco PostgreSQL da loja Shopee (impressão 3D sob demanda).

VIEWS DE AGREGAÇÃO (prefira-as para janelas de tempo — já tratam cancelamentos):
- vw_vendas_diarias_variacao (model_id, data DATE, pedidos, pedidos_cancelados, unidades_vendidas, receita_bruta)
  → vendas por variação/dia; unidades_vendidas e receita_bruta JÁ EXCLUEM pedidos cancelados.
- vw_funil_diario_item (item_id, data DATE, impressoes_org, cliques_org, visitantes_unicos, adicoes_carrinho,
  taxa_rejeicao, granularidade_trafego, impressoes_ads, cliques_ads, investimento_ads, gmv_ads,
  conversoes_ads, itens_vendidos_ads, granularidade_ads)
  → funil diário orgânico + pago por item (anúncio).

DIMENSÕES:
1. dim_produtos (item_id BIGINT PK, nome_atual, category_id, status_shopee, data_criacao,
   nota_media_estrelas, likes_count, dias_pre_encomenda)
2. dim_variacoes (model_id BIGINT PK, item_id FK, nome_variacao, sku_variacao, preco_venda_atual, estoque_shopee)
3. dim_materiais (id_material PK, nome, tipo, custo_por_unidade, unidade_medida, estoque_atual)
4. dim_maquinas (id_maquina PK, nome_modelo, custo_energia_hora)
5. map_engenharia_produto (model_id FK, id_material FK, id_maquina FK, peso_gramas,
   tempo_impressao_minutos, custo_embalagem, taxa_perda_percentual)

FATOS:
6. fato_pedidos_venda (order_sn PK, data_hora_criacao TIMESTAMP, uf_destino, status_pedido, motivo_cancelamento_devolucao)
7. fato_itens_pedido (order_sn FK, model_id FK, quantidade, preco_praticado)
8. fato_repasse_escrow (order_sn PK/FK, comissao_shopee, taxa_servico, taxa_transacao,
   custo_frete_reverso, lucro_liquido_absoluto) — repasse REAL da Shopee, nível do PEDIDO inteiro.
9. fato_trafego_diario (item_id FK, data DATE, impressoes NULL, cliques NULL, visitantes_unicos,
   taxa_rejeicao, adicoes_carrinho, granularidade_origem)
10. fato_ads_performance_produto (item_id FK, data_registro DATE, tipo_campanha 'GMV_MAX'|'PADRAO',
    nome_anuncio, impressoes NULL, cliques NULL, investimento, vendas_gmv, adicoes_carrinho,
    conversoes, itens_vendidos, roas, acos, granularidade_origem)
11. fato_historico_variacoes (model_id FK, data_registro DATE, preco_venda_atual, estoque_shopee)
    → foto diária de preço/estoque por variação.
12. fato_visao_geral_loja (data_registro DATE, metric_name, metric_value, fonte) — métricas macro da loja.
13. fato_metricas_produto_importadas (item_id FK, data_registro DATE, metric_name, metric_value, fonte)

MEMÓRIA DA IA:
14. log_acoes_shopee (id_log, item_id, model_id, tipo_acao, detalhe_acao, impacto_projetado JSONB,
    data_aplicacao, status_api, id_execucao_origem UUID)
15. ia_execucoes_analiticas (id_execucao UUID, criado_em, horizonte_dias, total_variacoes,
    cobertura_dados JSONB, resumo_executivo JSONB, status)
16. ia_snapshots_variacao (id_execucao FK, item_id, model_id, score_urgencia, qualidade_evidencia,
    tipo_acao_recomendada, metricas_observadas JSONB, previsoes JSONB, recomendacao JSONB)
17. ia_avaliacoes_acoes (id_log FK, model_id, baseline JSONB, previsto JSONB, observado JSONB,
    comparacao JSONB, status)

SEMÂNTICA IMPORTANTE:
- Pedidos cancelados: status_pedido IN ('CANCELLED','CANCELED','CANCELLED_BY_BUYER','IN_CANCEL').
- status_shopee do produto: 'NORMAL' = ativo; 'NAO_LISTADO' = saiu do ar; 'DELETADO' = só histórico.
- item_id = 0 em dim_produtos/ads é a entidade 'LOJA GLOBAL' (gasto de ads da loja, não de um produto).
- NULL em impressoes/cliques significa "dado não coletado", NUNCA zero medido.
- granularidade_origem: 'DIARIA' = observação real do dia; 'AGREGADA_PERIODO' = rateio de período maior.
- Custo de fabricação de uma variação = (peso_gramas convertido pela unidade_medida × custo_por_unidade)
  + (tempo_impressao_minutos × custo_energia_hora / 60) + custo_embalagem, tudo × (1 + taxa_perda_percentual/100).
- fato_ads_palavras_chave existe mas é legada e normalmente vazia — prefira fato_ads_performance_produto.
"""


# ══════════════════════════════════════════════════════════════════════════════
# SQL SOMENTE LEITURA
# ══════════════════════════════════════════════════════════════════════════════

def validar_sql_somente_leitura(query: str) -> str:
    """Impede múltiplas instruções e DML oculto em CTEs antes de tocar o banco."""
    sem_comentarios = re.sub(r"/\*.*?\*/|--[^\n]*", "", query, flags=re.DOTALL).strip()
    if not sem_comentarios:
        raise ValueError("A consulta SQL está vazia.")
    if sem_comentarios.endswith(";"):
        sem_comentarios = sem_comentarios[:-1].strip()
    if ";" in sem_comentarios:
        raise ValueError("O chat aceita somente uma instrução SQL por vez.")
    if not re.match(r"^(SELECT|WITH|EXPLAIN)\b", sem_comentarios, flags=re.IGNORECASE):
        raise ValueError("Por segurança, apenas consultas de leitura são permitidas.")
    proibidos = r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE|COPY|CALL|VACUUM)\b"
    if re.search(proibidos, sem_comentarios, flags=re.IGNORECASE):
        raise ValueError("A consulta contém um comando de escrita ou administração proibido.")
    # Bloco anônimo PL/pgSQL: só "DO $" é perigoso — a palavra "do" solta é
    # português legítimo em aliases ("AS "vendas do mês""), que o prompt pede.
    if re.search(r"\bDO\s*\$", sem_comentarios, flags=re.IGNORECASE):
        raise ValueError("A consulta contém um comando de escrita ou administração proibido.")
    return sem_comentarios


def executar_sql_leitura(query: str, max_linhas: int = 50) -> pd.DataFrame:
    """Executa uma consulta de leitura no pool com transação read-only e teto de 10s.

    SET LOCAL vale apenas para a transação corrente: a conexão volta ao pool
    sem estado residual (o statement_timeout global de 30s é restaurado).
    """
    query_segura = validar_sql_somente_leitura(query)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL transaction_read_only = on")
            cur.execute("SET LOCAL statement_timeout = '10s'")
            cur.execute(query_segura)
            if cur.description:
                colunas = [d[0] for d in cur.description]
                linhas = cur.fetchmany(max_linhas)
                return pd.DataFrame(linhas, columns=colunas)
    return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# CONTEXTO ESTRATÉGICO E PROMPT DE SISTEMA
# ══════════════════════════════════════════════════════════════════════════════

def obter_contexto_estrategico() -> str:
    """Últimas ações aplicadas + resumo da última auditoria do Cérebro IA."""
    partes = []
    try:
        acoes = executar_sql_leitura("""
            SELECT p.nome_atual AS produto, l.tipo_acao, l.detalhe_acao,
                   l.impacto_projetado AS projecao_ia, l.data_aplicacao
            FROM log_acoes_shopee l
            JOIN dim_produtos p ON l.item_id = p.item_id
            WHERE l.status_api = 'SUCESSO'
            ORDER BY l.data_aplicacao DESC
            LIMIT 10
        """)
        if acoes.empty:
            partes.append("Nenhuma ação foi aprovada e executada na loja recentemente.")
        else:
            acoes["data_aplicacao"] = acoes["data_aplicacao"].astype(str)
            partes.append("Últimas ações executadas na loja:\n" + acoes.to_json(orient="records", force_ascii=False))
    except Exception as exc:
        logger.warning(f"Contexto de ações indisponível para o chat: {exc}")
        partes.append("Diário de ações indisponível no momento.")

    try:
        auditoria = executar_sql_leitura("""
            SELECT criado_em, horizonte_dias, status, total_variacoes,
                   resumo_executivo->>'acoes_recomendadas' AS acoes_recomendadas,
                   resumo_executivo->>'resultado_operacional_observado' AS resultado_operacional
            FROM ia_execucoes_analiticas
            ORDER BY criado_em DESC
            LIMIT 1
        """)
        if not auditoria.empty:
            linha = auditoria.iloc[0]
            partes.append(
                f"Última auditoria do Cérebro IA: {linha['criado_em']} (horizonte {linha['horizonte_dias']}d, "
                f"status {linha['status']}, {linha['total_variacoes']} variações, "
                f"{linha['acoes_recomendadas'] or 0} ações recomendadas, "
                f"resultado operacional observado R$ {linha['resultado_operacional'] or 0})."
            )
    except Exception as exc:
        logger.warning(f"Resumo de auditoria indisponível para o chat: {exc}")
    return "\n".join(partes)


def construir_prompt_sistema() -> str:
    data_hoje = datetime.now().strftime("%Y-%m-%d")
    return f"""Você é o Consultor Analítico Sênior da loja Shopee de impressão 3D.
Converse com o dono da loja de forma direta, clara e orientada a lucro.

INFORMAÇÃO TEMPORAL: hoje é {data_hoje}. Para janelas relativas use CURRENT_DATE
(ex.: data >= CURRENT_DATE - INTERVAL '7 days').

CONTEXTO ESTRATÉGICO ATUAL:
{obter_contexto_estrategico()}

REGRAS DE FUNCIONAMENTO:
1. Se a resposta puder ser dada com o contexto acima ou conhecimento geral, responda direto em texto.
2. Para números da loja (vendas, lucro, tráfego, ads, estoque, histórico), escreva UMA query SQL
   de leitura entre as tags ```sql e ```. O sistema executa e devolve a tabela para você concluir.
3. Prefira as views vw_vendas_diarias_variacao e vw_funil_diario_item para janelas de tempo.
4. Sempre termine a query com LIMIT 50 e use aliases claros em português nas colunas.
5. Nunca invente tabelas ou colunas fora do schema; se o dado não existe, diga isso ao usuário.
6. NULL em impressões/cliques é "não coletado" — não trate como zero nem calcule CTR sobre NULL.
7. Lucro líquido real = lucro_liquido_absoluto do escrow − custo de fabricação (map_engenharia_produto
   + dim_materiais + dim_maquinas); o escrow é do pedido inteiro, cuidado ao atribuí-lo por item.
8. Na resposta final, seja executivo: número primeiro, contexto depois, sem citar SQL.

SCHEMA DO BANCO:
{SCHEMA_DO_BANCO}
"""


# ══════════════════════════════════════════════════════════════════════════════
# CHAMADA AO MODELO
# ══════════════════════════════════════════════════════════════════════════════

MAX_MENSAGENS_HISTORICO = 12


def chamar_chat(mensagens: list[dict], telemetria: dict | None = None) -> str:
    """Chamada única ao modelo de chat, preservando SEMPRE o prompt de sistema.

    Retorna o texto do modelo ou uma mensagem iniciada por '❌' em falha —
    quem decide como exibir é a interface.
    """
    if not config.OPENAI_API_KEY or config.OPENAI_API_KEY.lower().startswith("sua_chave"):
        return "❌ OPENAI_API_KEY não configurada no CHAVES_DADOS.env."

    sistema = [m for m in mensagens if m.get("role") == "system"][:1]
    conversa = [m for m in mensagens if m.get("role") != "system"][-MAX_MENSAGENS_HISTORICO:]
    payload = {
        "model": config.OPENAI_MODEL_CHAT,
        "messages": [{"role": m["role"], "content": m["content"]} for m in sistema + conversa],
        "max_completion_tokens": 2500,
    }
    if config.OPENAI_REASONING_CHAT in {"low", "medium", "high"}:
        payload["reasoning_effort"] = config.OPENAI_REASONING_CHAT
    headers = {"Authorization": f"Bearer {config.OPENAI_API_KEY}", "Content-Type": "application/json"}

    for tentativa in (1, 2):
        try:
            resposta = config.HTTP_SESSION.post(
                config.OPENAI_CHAT_COMPLETIONS_URL, headers=headers, json=payload, timeout=(10, 120),
            )
            if resposta.status_code == 400 and "reasoning_effort" in payload:
                payload.pop("reasoning_effort", None)
                continue
            if resposta.status_code == 429 and tentativa == 1:
                import time
                time.sleep(3)
                continue
            if resposta.status_code in {401, 403}:
                return "❌ Credencial OpenAI inválida ou sem permissão para o modelo configurado."
            resposta.raise_for_status()
            corpo = resposta.json()
            uso = corpo.get("usage") or {}
            if telemetria is not None:
                telemetria["chamadas"] = telemetria.get("chamadas", 0) + 1
                telemetria["prompt_tokens"] = telemetria.get("prompt_tokens", 0) + int(uso.get("prompt_tokens") or 0)
                telemetria["completion_tokens"] = telemetria.get("completion_tokens", 0) + int(uso.get("completion_tokens") or 0)
            return corpo["choices"][0]["message"]["content"].strip()
        except requests.exceptions.Timeout:
            return "❌ A OpenAI demorou demais para responder. Tente novamente."
        except requests.exceptions.RequestException as exc:
            if tentativa == 1:
                continue
            return f"❌ Falha de rede ao consultar a OpenAI: {exc}"
        except Exception as exc:
            return f"❌ Erro inesperado no chat: {exc}"
    return "❌ Não foi possível obter resposta do modelo."


def extrair_sql(texto: str) -> str | None:
    match = re.search(r"```sql\s*(.*?)\s*```", texto or "", re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None


# ══════════════════════════════════════════════════════════════════════════════
# TURNO COMPLETO (padrão ReAct com 1 rodada de reparo de SQL)
# ══════════════════════════════════════════════════════════════════════════════

LIMITE_CARACTERES_TABELA = 3_800


def _tabela_para_modelo(df: pd.DataFrame) -> str:
    if df.empty:
        return "A consulta retornou zero linhas. Não há dados para esse filtro."
    tabela = df.to_markdown(index=False)
    if len(tabela) > LIMITE_CARACTERES_TABELA:
        tabela = tabela[:LIMITE_CARACTERES_TABELA] + "\n... (tabela truncada em 50 linhas/3.800 caracteres)"
    return tabela


def executar_turno(historico: list[dict], ao_evento=None, telemetria: dict | None = None) -> list[dict]:
    """Processa um turno do usuário e retorna as mensagens novas a anexar.

    Mensagens com "oculta": True fazem parte do contexto do modelo (SQL bruto,
    tabelas, pedidos de correção) mas não devem ser renderizadas no chat.

    ao_evento(tipo, dado) com tipo em {"sql", "tabela", "erro_sql"} permite à
    UI mostrar o processo em tempo real. Custo máximo: 3 chamadas por turno.
    """
    notificar = ao_evento or (lambda tipo, dado: None)
    novas: list[dict] = []

    resposta = chamar_chat(historico, telemetria)
    sql = extrair_sql(resposta) if not resposta.startswith("❌") else None
    if not sql:
        novas.append({"role": "assistant", "content": resposta})
        return novas

    tabela = None
    for tentativa in (1, 2):
        notificar("sql", sql)
        novas.append({"role": "assistant", "content": resposta, "oculta": True})
        try:
            df = executar_sql_leitura(sql)
            tabela = _tabela_para_modelo(df)
            notificar("tabela", df)
            break
        except Exception as erro:
            notificar("erro_sql", str(erro))
            if tentativa == 2:
                tabela = f"Erro na execução do SQL: {erro}"
                break
            novas.append({
                "role": "user", "oculta": True,
                "content": (
                    f"O PostgreSQL rejeitou a consulta com o erro: {erro}. "
                    "Corrija e devolva apenas a query corrigida entre ```sql e ```."
                ),
            })
            resposta = chamar_chat(historico + novas, telemetria)
            sql = extrair_sql(resposta) if not resposta.startswith("❌") else None
            if not sql:
                novas.append({"role": "assistant", "content": resposta})
                return novas

    novas.append({
        "role": "user", "oculta": True,
        "content": (
            f"Resultado do PostgreSQL:\n{tabela}\n"
            "Formule a resposta final ao usuário de forma clara e executiva, sem citar SQL."
        ),
    })
    resposta_final = chamar_chat(historico + novas, telemetria)
    novas.append({"role": "assistant", "content": resposta_final})
    return novas
