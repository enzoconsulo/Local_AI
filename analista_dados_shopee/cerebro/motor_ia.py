"""
cerebro/motor_ia.py
===================
Comunicação com a API OpenAI e disciplina de custo:

  - Gatekeeper: produtos sem atividade nem gasto são resolvidos localmente,
    sem gastar um único token.
  - Smart batching: lotes pequenos por horizonte (7d: mais SKUs e reasoning
    low; 30d: menos SKUs e reasoning medium) com payload compactado.
  - JSON mode + validação de completude: a resposta precisa devolver
    exatamente um objeto por SKU enviado, ou o lote é rejeitado.
  - Normalização defensiva: nenhum valor do LLM alcança interface, cache ou
    API Shopee sem passar por tipos, limites e vocabulário de ações.
"""

import json
import math
import time

import requests
from loguru import logger

from cerebro import config
from cerebro.heuristicas import (
    calcular_dias_estoque,
    calcular_score_urgencia,
    classificar_confianca_evidencia,
)


# ══════════════════════════════════════════════════════════════════════════════
# VALIDAÇÃO E CONFIGURAÇÃO
# ══════════════════════════════════════════════════════════════════════════════

def validar_sugestao_ia(dados: dict, analise: dict) -> tuple[bool, str]:
    """Camada de segurança em código: limites duros independentes do modelo.
    BLINDAGEM ANTI-NULL: mesmo se a IA devolver 'null', o sistema não quebra."""
    preco_atual      = float(dados.get("preco_atual") or 0)
    capacidade_max   = int(dados.get("LOGISTICA_capacidade_material_restante") or 999_999)

    np_raw           = analise.get("novo_preco_sugerido")
    novo_preco       = float(np_raw) if np_raw is not None else preco_atual

    pv_raw           = analise.get("previsao_vendas_7d")
    previsao_vendas  = int(pv_raw) if pv_raw is not None else 0

    if novo_preco is None or novo_preco <= 0:
        return False, "Preço sugerido é inválido (zero, negativo ou ausente)."

    if preco_atual > 0:
        variacao = abs(novo_preco - preco_atual) / preco_atual
        if variacao > 0.80:
            return False, (
                f"Variação de {variacao * 100:.0f}% no preço excede o limite "
                f"de segurança de 80%. Ajuste manual necessário."
            )

    if previsao_vendas > 0 and capacidade_max < 999_999:
        if previsao_vendas > capacidade_max:
            return False, (
                f"Previsão de {previsao_vendas} un. excede a capacidade de "
                f"fábrica ({capacidade_max} un. de material restante)."
            )

    return True, ""


def configuracao_openai_valida() -> tuple[bool, str]:
    """Valida credenciais localmente e retorna (ok, motivo) sem tocar na UI —
    a camada de interface decide como exibir o problema."""
    if not config.OPENAI_API_KEY or config.OPENAI_API_KEY.lower().startswith("sua_chave"):
        return False, "OPENAI_API_KEY não foi configurada. Adicione a chave ao CHAVES_DADOS.env e reinicie o app."
    if not config.OPENAI_MODEL_7D or not config.OPENAI_MODEL_30D:
        return False, "Defina OPENAI_MODEL_7D e OPENAI_MODEL_30D no CHAVES_DADOS.env."
    return True, ""


# ══════════════════════════════════════════════════════════════════════════════
# COMPACTAÇÃO DO PAYLOAD (menos tokens de entrada por lote)
# ══════════════════════════════════════════════════════════════════════════════

def resumir_memoria_para_prompt(memoria: dict | None) -> dict | None:
    """Mantém o aprendizado útil sem reenviar relatórios extensos a cada leitura de 7 dias."""
    if not isinstance(memoria, dict):
        return None
    recomendacao = memoria.get("recomendacao") or {}
    return {
        "ultima_analise_30d_em": memoria.get("ultima_analise_30d_em"),
        "qualidade_evidencia": memoria.get("qualidade_evidencia"),
        "previsoes": memoria.get("previsoes") or {},
        "decisao_anterior": {
            chave: recomendacao.get(chave)
            for chave in ("tipo_acao", "novo_preco_sugerido", "recomendacao_executiva", "cluster_mercado")
            if recomendacao.get(chave) is not None
        },
        "avaliacao_da_acao": {
            "status": memoria.get("status_ultima_avaliacao"),
            "comparacao": memoria.get("comparacao_ultima_acao") or {},
        },
    }


CAMPOS_PROMPT_7D = {
    "model_id", "nome_variacao", "preco_atual", "custo_fabricacao_unitario",
    "vendas_7d_reais", "tendencia_vendas_WoW_perc", "lucro_liquido_real_7d",
    "trafego_visitas_7d", "trafego_conversao_perc", "abandono_carrinho_perc",
    "ads_gasto_7d", "retorno_liquido_por_ads", "taxa_cancelamento_7d_perc",
    "estoque_shopee_hoje", "LOGISTICA_capacidade_material_restante",
    "LOGISTICA_dias_estoque_restante", "previsao_deterministica_vendas_7d",
    "previsao_deterministica_lucro_7d",
    "funil_organico_impressoes", "funil_organico_cliques", "funil_organico_ctr_perc",
    "funil_ads_impressoes", "funil_ads_cliques", "funil_ads_ctr_perc",
    "funil_ads_acos_medio", "qualidade_evidencia", "limite_evidencia",
    "historico_acoes_passadas", "memoria_estrategica_30d",
    # Sinais decisivos da camada de correlação (v3): poucos tokens, muito veto.
    "margem_unitaria_perc", "share_variacao_30d_perc",
    "dias_estoque_shopee", "curva_abc", "em_promocao_tipo",
}


def compactar_lote_por_horizonte(lote_json: list[dict], horizonte: str) -> list[dict]:
    """Envia ao modelo apenas os sinais necessários ao horizonte solicitado."""
    resultado = []
    for produto in lote_json:
        variacoes = produto.get("variacoes_ativas", [])
        if horizonte == "7d":
            variacoes = [{k: v for k, v in variacao.items() if k in CAMPOS_PROMPT_7D} for variacao in variacoes]
            for variacao in variacoes:
                variacao["memoria_estrategica_30d"] = resumir_memoria_para_prompt(
                    variacao.get("memoria_estrategica_30d")
                )
        resultado.append({
            "item_id": produto.get("item_id"),
            "nome_produto": produto.get("nome_produto"),
            "horizonte_solicitado": horizonte,
            # Correlações medidas do anúncio: enviadas UMA vez por produto (e não
            # replicadas por SKU) — máximo de contexto por token gasto.
            "sinais_produto": produto.get("sinais_produto", {}),
            "metricas_macro_produto_30_dias": produto.get("metricas_macro_produto_30_dias", {}) if horizonte == "30d" else {},
            "variacoes_ativas": variacoes,
        })
    return resultado


# ══════════════════════════════════════════════════════════════════════════════
# PROMPT
# ══════════════════════════════════════════════════════════════════════════════

def construir_prompt_otimizado(horizonte: str) -> str:
    """Prompt curto e determinístico para maximizar prefix cache e reduzir tokens."""
    base = """Você é um conselho CFO/CMO/COO para uma loja Shopee de impressão 3D sob demanda.
Analise apenas os dados JSON fornecidos. Seja matemático, específico e conciso.

REGRAS:
1. null = dado não coletado; nunca converta null em zero nem infira CTR, shadowban ou baixa descoberta.
2. CTR só existe com impressões > 0 e cliques numéricos. Correlação não prova causalidade.
3. Estoque é virtual e depende de filamento compartilhado; produto sem vendas não imobiliza estoque acabado.
4. Considere custo de fabricação, taxa Shopee aproximada de 20% + R$3 e margem mínima de segurança de 15%.
5. Sem gasto em ads, não fale em ROAS nem recomende pausar campanha. Com gasto e retorno ruim, ação de ads é apenas manual.
6. Tráfego e ads são medidos no anúncio e chegam rateados por variação (metade igualitário, metade proporcional às vendas de 30d); trate-os como sinal, não como atribuição exata.
7. Ações permitidas: AUMENTAR_PRECO, REDUZIR_PRECO, CRIAR_PROMOCAO, CRIAR_COMBO, PAUSAR_ADS ou MANTER.
8. A previsão determinística é a âncora. Só se afaste dela quando um dado explícito justificar, explicando o motivo.
9. Retorne somente um objeto JSON válido no formato {"resultados":[...]}, com exatamente um objeto por model_id. Sem markdown ou texto externo.
10. Não confunda métricas de ads: funil_ads_acos_medio avalia só a campanha (gasto/GMV atribuído ao anúncio); retorno_liquido_por_ads é o lucro líquido TOTAL dividido pelo gasto. Retorno líquido alto com ACOS moderado não caracteriza ads fraco.
11. margem_unitaria_perc (preço − taxa Shopee − fabricação, em % do preço) é o ACOS de equilíbrio do SKU: ads só é rentável com funil_ads_acos_medio abaixo dela; acima, trate como perda de margem por venda.
12. sinais_produto são correlações MEDIDAS do anúncio (melhor dia de venda, parceiro real de cesta, UF dominante, views da API, recompra, preparo/atraso de envio, devoluções). Use-as para timing de promoção, segmentação e pareceres de operações. Só recomende CRIAR_COMBO com cesta_pedidos_conjuntos_180d >= 2 (cite o parceiro) ou entre variações do próprio anúncio.
13. em_promocao_tipo != null indica promoção Shopee VIGENTE no SKU: não proponha CRIAR_PROMOCAO nem REDUZIR_PRECO por cima dela, e trate preço corrente e elasticidade do período como efeito da promoção, não como reprecificação.
"""
    if horizonte == "7d":
        return base + """
HORIZONTE: próximos 7 dias. Gere intervenção tática, reversível e objetiva.
Campos obrigatórios por objeto: item_id, model_id, tipo_acao, novo_preco_sugerido,
horas_duracao_promocao, previsao_vendas_7d, previsao_lucro_7d,
elasticidade_preco_volume, cluster_mercado, recomendacao_executiva,
relatorio_cfo_financas, relatorio_cmo_marketing, relatorio_coo_operacoes,
plano_curto_prazo_7d (máximo 3 passos) e analise_de_consequencias.
Limites: cada parecer até 240 caracteres; recomendação até 350; consequência até 300; cada passo até 180.
Não produza campos ou plano de 30 dias.
"""
    return base + """
HORIZONTE: próximos 30 dias. Use o realizado mensal como base e os 7 dias apenas como sinal recente.
Campos obrigatórios por objeto: item_id, model_id, tipo_acao, novo_preco_sugerido,
horas_duracao_promocao, previsao_vendas_7d, previsao_lucro_7d,
previsao_vendas_30d, previsao_lucro_30d, elasticidade_preco_volume,
cluster_mercado, recomendacao_executiva, relatorio_cfo_financas,
relatorio_cmo_marketing, relatorio_coo_operacoes, plano_curto_prazo_7d,
plano_longo_prazo_30d e analise_de_consequencias.
Limites: cada relatório até 500 caracteres; plano mensal até 4 passos verificáveis.
O plano mensal nunca é executável automaticamente.
"""


# ══════════════════════════════════════════════════════════════════════════════
# PARSE, FALLBACK E NORMALIZAÇÃO DA SAÍDA
# ══════════════════════════════════════════════════════════════════════════════

def extrair_array_json_resposta(texto: str) -> list[dict]:
    """Extrai a lista de resultados do JSON mode, aceitando legado em array puro."""
    def obter_resultados(carregado) -> list[dict] | None:
        if isinstance(carregado, list):
            return carregado
        if isinstance(carregado, dict) and isinstance(carregado.get("resultados"), list):
            return carregado["resultados"]
        return None

    limpo = texto.replace("```json", "").replace("```", "").strip()
    try:
        carregado = json.loads(limpo)
        resultados = obter_resultados(carregado)
        if resultados is not None:
            return resultados
    except json.JSONDecodeError:
        pass
    inicios = [pos for pos in (limpo.find("["), limpo.find("{")) if pos >= 0]
    if not inicios:
        raise ValueError("A resposta não contém JSON estruturado.")
    inicio = min(inicios)
    carregado, _ = json.JSONDecoder().raw_decode(limpo[inicio:])
    resultados = obter_resultados(carregado)
    if resultados is None:
        raise ValueError("A resposta JSON não contém a lista 'resultados'.")
    return resultados


def gerar_fallback_lote(lote_json: list[dict], horizonte: str, motivo: str) -> list[dict]:
    """Mantém a auditoria utilizável quando o endpoint falha, sem inventar análise."""
    resultados = []
    for produto in lote_json:
        for variacao in produto.get("variacoes_ativas", []):
            preco = float(variacao.get("preco_atual") or 0)
            resultados.append({
                "item_id": produto.get("item_id"),
                "model_id": variacao.get("model_id"),
                "tipo_acao": "MANTER",
                "novo_preco_sugerido": preco,
                "horas_duracao_promocao": 0,
                "previsao_vendas_7d": variacao.get("previsao_deterministica_vendas_7d", 0),
                "previsao_lucro_7d": variacao.get("previsao_deterministica_lucro_7d", 0.0),
                "previsao_vendas_30d": variacao.get("previsao_deterministica_vendas_30d", 0),
                "previsao_lucro_30d": variacao.get("previsao_deterministica_lucro_30d", 0.0),
                "plano_curto_prazo_7d": ["Repetir a análise quando o endpoint de IA estiver disponível."],
                "plano_longo_prazo_30d": [] if horizonte == "7d" else ["Preservar a estratégia atual até nova análise completa."],
                "elasticidade_preco_volume": variacao.get("elasticidade_preco_volume", 0),
                "cluster_mercado": "Análise indisponível",
                "recomendacao_executiva": "Nenhuma mudança automática foi recomendada porque a análise externa não foi concluída.",
                "analise_de_consequencias": motivo,
                "falha_modelo_externo": True,
            })
    return resultados


def normalizar_saida_modelo(recomendacao: dict, dados: dict) -> dict:
    """Normaliza tipos e ações antes que qualquer saída do LLM alcance interface ou API."""
    resultado = dict(recomendacao)
    alertas = []

    def numero_finito(valor, padrao: float) -> float:
        try:
            convertido = float(valor)
            return convertido if math.isfinite(convertido) else float(padrao)
        except (TypeError, ValueError):
            return float(padrao)

    acao = str(resultado.get("tipo_acao") or "MANTER").strip().upper()
    if acao not in config.ACOES_VALIDAS:
        alertas.append(f"Ação desconhecida '{acao}' substituída por MANTER.")
        acao = "MANTER"
    resultado["tipo_acao"] = acao

    preco_atual = numero_finito(dados.get("preco_atual"), 0)
    novo_preco = numero_finito(resultado.get("novo_preco_sugerido"), preco_atual)
    if novo_preco <= 0:
        alertas.append("Preço inválido substituído pelo preço atual.")
        novo_preco = preco_atual
    resultado["novo_preco_sugerido"] = round(novo_preco, 2)

    for campo, padrao in (
        ("previsao_vendas_7d", dados.get("previsao_vendas_7d", 0)),
        ("previsao_vendas_30d", dados.get("previsao_vendas_30d", 0)),
    ):
        resultado[campo] = max(0, int(round(numero_finito(resultado.get(campo), padrao))))
    for campo, padrao in (
        ("previsao_lucro_7d", dados.get("previsao_lucro_7d", 0)),
        ("previsao_lucro_30d", dados.get("previsao_lucro_30d", 0)),
        ("elasticidade_preco_volume", dados.get("elasticidade_preco_volume", 0)),
    ):
        resultado[campo] = round(numero_finito(resultado.get(campo), padrao), 4)

    duracao = int(round(numero_finito(resultado.get("horas_duracao_promocao"), 0)))
    resultado["horas_duracao_promocao"] = max(0, min(168, duracao))

    for campo in ("plano_curto_prazo_7d", "plano_longo_prazo_30d", "plano_acao_shopee"):
        valor = resultado.get(campo, [])
        if isinstance(valor, str):
            valor = [valor]
        elif not isinstance(valor, list):
            valor = []
        resultado[campo] = [str(item)[:500] for item in valor if item is not None][:6]

    for campo in (
        "cluster_mercado", "recomendacao_executiva", "analise_de_consequencias",
        "relatorio_cfo_financas", "relatorio_cmo_marketing", "relatorio_coo_operacoes",
    ):
        valor = resultado.get(campo)
        if valor is not None:
            resultado[campo] = str(valor)[:2000]

    # Preserva a marcação de fallback: um lote que falhou NÃO pode ser
    # normalizado para "sucesso", ou o cache semântico reutilizaria um MANTER
    # de emergência como se fosse análise genuína, congelando o SKU.
    resultado["falha_modelo_externo"] = bool(recomendacao.get("falha_modelo_externo", False))
    if alertas:
        resultado["alerta_validacao_modelo"] = " ".join(alertas)
    return resultado


# ══════════════════════════════════════════════════════════════════════════════
# CHAMADA À API OPENAI
# ══════════════════════════════════════════════════════════════════════════════

def _limite_tokens_saida(horizonte: str, total_variacoes: int) -> int:
    """Teto de segurança da resposta — não é gasto garantido (paga-se só o usado).

    Modelos gpt-5.x com reasoning consomem parte de max_completion_tokens em
    tokens de raciocínio invisíveis ANTES do JSON. Um teto apertado trunca a
    resposta no meio, o parse falha e a requisição inteira (já paga) é
    desperdiçada. A folga abaixo reserva orçamento de raciocínio (baixo no 7d,
    médio no 30d) além do JSON estimado por SKU.
    """
    if horizonte == "7d":
        return min(8_000, 1_500 + 700 * total_variacoes)
    return min(12_000, 2_500 + 1_700 * total_variacoes)


def chamar_cerebro_openai_preditivo(
    lote_json: list[dict], horizonte: str = "7d", max_tentativas: int = 2,
    telemetria: dict | None = None,
) -> list[dict]:
    """Executa a análise via API OpenAI com JSON mode, sem dependência de GPU remota."""
    config.horizonte_em_dias(horizonte)  # valida o horizonte

    modelo = config.modelo_para(horizonte)
    esforco_raciocinio = config.reasoning_para(horizonte)
    timeout_request = 180 if horizonte == "7d" else 300

    lote_compacto = compactar_lote_por_horizonte(lote_json, horizonte)
    total_variacoes = sum(len(p.get("variacoes_ativas", [])) for p in lote_compacto)
    max_tokens = _limite_tokens_saida(horizonte, total_variacoes)
    prompt_sistema = construir_prompt_otimizado(horizonte)
    auditoria_json = json.dumps(lote_compacto, ensure_ascii=False, separators=(",", ":"), default=str)

    payload = {
        "model": modelo,
        "messages": [
            {"role": "system", "content": prompt_sistema},
            {"role": "user", "content": f"Auditoria:{auditoria_json}"},
        ],
        "max_completion_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    if esforco_raciocinio in {"low", "medium", "high"}:
        payload["reasoning_effort"] = esforco_raciocinio
    headers = {
        "Authorization": f"Bearer {config.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    tentativas_executadas = 0
    fallback_sem_reasoning = False
    for tentativa in range(1, max_tentativas + 1):
        tentativas_executadas = tentativa
        try:
            logger.info(
                f"🧠 [OPENAI:{modelo}] Processando {total_variacoes} SKU(s) em {len(lote_json)} produto(s) "
                f"(tentativa {tentativa}/{max_tentativas})..."
            )

            response = config.HTTP_SESSION.post(
                config.OPENAI_CHAT_COMPLETIONS_URL,
                headers=headers,
                json=payload,
                timeout=(10, timeout_request),
            )
            if response.status_code == 400 and "reasoning_effort" in payload and not fallback_sem_reasoning:
                logger.warning("A API rejeitou reasoning_effort; repetindo uma única vez sem esse parâmetro.")
                payload.pop("reasoning_effort", None)
                fallback_sem_reasoning = True
                continue
            if response.status_code in {401, 403}:
                logger.error("🔴 [OPENAI] Credencial inválida ou sem permissão para o modelo configurado.")
                break
            if response.status_code == 429:
                try:
                    espera = int(response.headers.get("Retry-After", "3") or 3)
                except (TypeError, ValueError):
                    espera = 3
                espera = min(15, max(1, espera))
                logger.warning(f"🟠 [OPENAI] Limite temporário atingido; aguardando {espera}s.")
                time.sleep(espera)
                continue
            if 400 <= response.status_code < 500:
                logger.error(
                    f"🔴 [OPENAI] Requisição rejeitada ({response.status_code}): "
                    f"{response.text[:300]}"
                )
                break
            response.raise_for_status()

            corpo_resposta = response.json()
            texto = corpo_resposta["choices"][0]["message"]["content"].strip()
            resultado = extrair_array_json_resposta(texto)
            chaves_esperadas = {
                (int(p["item_id"]), int(v["model_id"]))
                for p in lote_json for v in p.get("variacoes_ativas", [])
                if p.get("item_id") is not None and v.get("model_id") is not None
            }
            chaves_recebidas = {
                (int(r["item_id"]), int(r["model_id"]))
                for r in resultado
                if isinstance(r, dict) and r.get("item_id") is not None and r.get("model_id") is not None
            }
            if chaves_recebidas != chaves_esperadas or len(resultado) != len(chaves_esperadas):
                raise ValueError(
                    f"Resposta incompleta: esperados {len(chaves_esperadas)} SKUs, "
                    f"recebidos {len(chaves_recebidas)} pares válidos de produto/SKU."
                )
            uso = corpo_resposta.get("usage") or {}
            if telemetria is not None:
                telemetria["chamadas"] = telemetria.get("chamadas", 0) + 1
                telemetria["prompt_tokens"] = telemetria.get("prompt_tokens", 0) + int(uso.get("prompt_tokens") or 0)
                telemetria["completion_tokens"] = telemetria.get("completion_tokens", 0) + int(uso.get("completion_tokens") or 0)
            logger.success(
                f"✅ [OPENAI:{modelo}] Lote concluído. "
                f"Tokens entrada/saída: {uso.get('prompt_tokens', 'n/d')}/{uso.get('completion_tokens', 'n/d')}."
            )
            return resultado

        except requests.exceptions.Timeout:
            logger.error(f"🔴 [OPENAI] Timeout na tentativa {tentativa}; não haverá reenvio ambíguo para evitar custo duplicado.")
            break

        except requests.exceptions.RequestException as e:
            logger.error(f"🔴 [OPENAI] Falha de rede na tentativa {tentativa}: {e}")

        except json.JSONDecodeError as e:
            logger.error(f"🔴 [OPENAI] IA retornou JSON inválido na tentativa {tentativa}: {e}")

        except Exception as e:
            logger.error(f"🔴 [OPENAI] Erro inesperado na tentativa {tentativa}: {e}")

        if tentativa < max_tentativas:
            logger.info("⏳ Aguardando 5 segundos antes de tentar novamente...")
            time.sleep(5)

    mensagem_critica = f"A IA externa não concluiu o lote após {tentativas_executadas} tentativa(s)."
    logger.error(mensagem_critica)
    if telemetria is not None:
        telemetria["lotes_falhos"] = telemetria.get("lotes_falhos", 0) + 1
    return gerar_fallback_lote(lote_json, horizonte, mensagem_critica)


# ══════════════════════════════════════════════════════════════════════════════
# AGRUPAMENTO, GATEKEEPER E LOTES
# ══════════════════════════════════════════════════════════════════════════════

def _variacao_para_payload(var: dict) -> dict:
    """Projeção de uma variação do dossiê para o payload da IA (com blindagem de nulos)."""
    return {
        "model_id": var["model_id"],
        "nome_variacao": var["nome_variacao"],
        "preco_atual": var["preco_atual"],
        "custo_fabricacao_unitario": var.get("custo_fab_real", 0),
        "preco_tendencia_7d_perc": var.get("preco_tendencia_7d_perc", 0),
        "vendas_30d_reais": var["vendas_30d_macro"],
        "vendas_7d_reais": var["vendas_7d_reais"],
        "cobertura_dias_trafego_30d": var.get("COBERTURA_dias_trafego_30d", 0),
        "cobertura_dias_com_venda_30d": var.get("COBERTURA_dias_com_venda_30d", 0),
        "tendencia_vendas_WoW_perc": var.get("tendencia_vendas_WoW_perc", 0),
        "ritmo_7d_vs_30d_perc": var.get("ritmo_7d_vs_30d_perc", 0),
        "lucro_liquido_real_7d": var["lucro_liquido_real_7d"],
        "lucro_liquido_real_30d": var.get("lucro_liquido_real_30d", 0),

        "funil_organico_impressoes": var.get("TRAFEGO_ORG_impressoes_7d"),
        "funil_organico_cliques": var.get("TRAFEGO_ORG_cliques_7d"),
        "funil_organico_ctr_perc": var.get("TRAFEGO_ORG_ctr_perc"),
        "funil_organico_rejeicao_perc": var.get("TRAFEGO_ORG_taxa_rejeicao_perc"),
        "funil_organico_impressoes_30d": var.get("TRAFEGO_ORG_impressoes_30d"),
        "funil_organico_cliques_30d": var.get("TRAFEGO_ORG_cliques_30d"),
        "funil_organico_ctr_30d_perc": var.get("TRAFEGO_ORG_ctr_30d_perc"),
        "funil_ads_impressoes": var.get("ADS_impressoes_7d"),
        "funil_ads_cliques": var.get("ADS_cliques_7d"),
        "funil_ads_ctr_perc": var.get("ADS_ctr_perc"),
        "funil_ads_acos_medio": var.get("ADS_acos_medio"),
        "funil_ads_impressoes_30d": var.get("ADS_impressoes_30d"),
        "funil_ads_cliques_30d": var.get("ADS_cliques_30d"),
        "funil_ads_ctr_30d_perc": var.get("ADS_ctr_30d_perc"),
        "funil_ads_gmv_30d": var.get("ADS_gmv_30d"),

        "trafego_visitas_7d": var.get("TRAFEGO_visitas_7d", 0),
        "trafego_conversao_perc": var.get("TRAFEGO_taxa_conversao_perc", 0),
        "abandono_carrinho_perc": var.get("taxa_abandono_carrinho_perc", 0),
        "trafego_visitas_30d": var.get("TRAFEGO_visitas_30d", 0),
        "trafego_conversao_30d_perc": var.get("TRAFEGO_taxa_conversao_30d_perc", 0),
        "abandono_carrinho_30d_perc": var.get("taxa_abandono_carrinho_30d_perc", 0),
        "ads_gasto_7d": var.get("ADS_gasto_7d", 0),
        "retorno_liquido_por_ads": var.get("ADS_roas_atual", 0),
        "ads_gasto_30d": var.get("ADS_gasto_30d", 0),
        "retorno_liquido_por_ads_30d": var.get("ADS_retorno_liquido_30d", 0),
        "elasticidade_preco_volume": var.get("elasticidade_preco_volume", 0),
        "taxa_cancelamento_7d_perc": var["taxa_cancelamento_7d_perc"],
        "taxa_cancelamento_30d_perc": var.get("taxa_cancelamento_30d_perc", 0),
        "estoque_shopee_hoje": var["estoque_shopee_hoje"],
        "LOGISTICA_capacidade_material_restante": var["LOGISTICA_capacidade_material_restante"],
        "LOGISTICA_dias_estoque_restante": var["LOGISTICA_dias_estoque_restante"],
        "LOGISTICA_dias_estoque_base_30d": var.get("LOGISTICA_dias_estoque_base_30d", 999),
        "previsao_deterministica_vendas_7d": var.get("previsao_vendas_7d", 0),
        "previsao_deterministica_lucro_7d": var.get("previsao_lucro_7d", 0),
        "previsao_deterministica_vendas_30d": var.get("previsao_vendas_30d", 0),
        "previsao_deterministica_lucro_30d": var.get("previsao_lucro_30d", 0),
        "margem_unitaria_perc": var.get("FINANCEIRO_margem_unitaria_perc", 0),
        "share_variacao_30d_perc": var.get("PORTFOLIO_share_variacao_30d_perc"),
        "dias_estoque_shopee": var.get("LOGISTICA_dias_estoque_shopee", 999),
        "curva_abc": var.get("PORTFOLIO_curva_abc"),
        "em_promocao_tipo": var.get("PROMO_ativa_tipo"),
        "qualidade_evidencia": classificar_confianca_evidencia(var)[0],
        "limite_evidencia": classificar_confianca_evidencia(var)[1],
        "historico_acoes_passadas": var["historico_acoes_passadas"],
        "memoria_estrategica_30d": var.get("MEMORIA_ESTRATEGICA_30D"),
    }


def _agrupar_por_produto(dossie_completo: list[dict]) -> dict:
    """Agrupa variações pelo produto pai, com macro de 30 dias e score máximo."""
    produtos_agrupados = {}
    for var in dossie_completo:
        iid = var["item_id"]
        if iid not in produtos_agrupados:
            produtos_agrupados[iid] = {
                "item_id": iid,
                "nome_produto": var["nome_produto"],
                "score_urgencia_maximo": 0,
                "metricas_macro_produto_30_dias": {
                    "visitas_totais_30d": var.get("visitas_30d_macro", 0),
                    "adicoes_carrinho_totais_30d": var.get("carrinhos_30d_macro", 0),
                    "gasto_ads_total_30d": round(var.get("gasto_ads_30d_macro", 0), 2),
                    "dias_trafego_coletados_30d": var.get("COBERTURA_dias_trafego_30d", 0),
                    "estrelas": var.get("REPUTACAO_estrelas", 0),
                    "favoritos": var.get("REPUTACAO_curtidas_favoritos", 0)
                },
                # Correlações medidas no nível do anúncio (iguais em todas as
                # variações do item): gravadas uma única vez por produto.
                "sinais_produto": {
                    "melhor_dia_semana": var.get("VENDAS_melhor_dia_semana"),
                    "share_melhor_dia_perc": var.get("VENDAS_share_melhor_dia_perc"),
                    "cesta_parceiro_top": var.get("CESTA_parceiro_top"),
                    "cesta_pedidos_conjuntos_180d": var.get("CESTA_pedidos_conjuntos_180d", 0),
                    "uf_top": var.get("GEO_uf_top"),
                    "uf_top_share_perc": var.get("GEO_uf_top_share_perc"),
                    "api_views_7d": var.get("API_views_7d"),
                    "api_curtidas_7d": var.get("API_curtidas_7d"),
                    "recompra_perc_180d": var.get("POSVENDA_recompra_perc_180d"),
                    "preparo_mediano_horas": var.get("POSVENDA_preparo_mediano_horas"),
                    "preparo_atrasado_perc": var.get("POSVENDA_preparo_atrasado_perc"),
                    "entrega_mediana_dias": var.get("POSVENDA_entrega_mediana_dias"),
                    "devolucoes_90d": var.get("POSVENDA_devolucoes_90d", 0),
                    "devolucao_motivo": var.get("POSVENDA_devolucao_motivo"),
                },
                "variacoes_ativas": []
            }

        score_var = calcular_score_urgencia(var)
        produtos_agrupados[iid]["score_urgencia_maximo"] = max(
            produtos_agrupados[iid]["score_urgencia_maximo"], score_var
        )
        produtos_agrupados[iid]["variacoes_ativas"].append(_variacao_para_payload(var))
    return produtos_agrupados


def _resolver_fantasma_local(p: dict, originais_por_chave: dict) -> list[dict]:
    """Produto sem atividade nem gasto: parecer local completo, custo zero de API."""
    macro = p["metricas_macro_produto_30_dias"]
    cobertura_trafego = int(macro.get("dias_trafego_coletados_30d", 0) or 0)
    topo_mensuravel = any(
        v.get("funil_organico_impressoes_30d") is not None
        for v in p["variacoes_ativas"]
    )
    resultados = []
    for var in p["variacoes_ativas"]:
        original = originais_por_chave.get((int(p["item_id"]), int(var["model_id"])))
        if not original:
            continue
        resultados.append({
            "item_id": p["item_id"],
            "model_id": var["model_id"],
            "tipo_acao": "MANTER",
            "novo_preco_sugerido": var["preco_atual"],
            "previsao_vendas_7d": 0,
            "previsao_lucro_7d": 0.0,
            "previsao_vendas_30d": 0,
            "previsao_lucro_30d": 0.0,
            "plano_curto_prazo_7d": ["Validar título, atributos e imagem de capa antes de investir em mídia."],
            "plano_longo_prazo_30d": ["Reavaliar descoberta após 30 dias com dados de impressões e cliques, se disponíveis."],
            "elasticidade_preco_volume": 0.0,
            "cluster_mercado": "Baixa atividade observada",
            "recomendacao_executiva": "Há pouca atividade observada com cobertura suficiente; valide descoberta e atratividade antes de alterar preço.",
            "relatorio_cfo_financas": "Sem vendas observadas; não há evidência suficiente para atribuir o resultado ao preço.",
            "relatorio_cmo_marketing": (
                f"Foram observadas {macro['visitas_totais_30d']} visitas em "
                f"{cobertura_trafego or 30} dia(s) de referência. "
                + ("O topo do funil está mensurado." if topo_mensuravel else "Impressões/cliques estão indisponíveis; não foi inferido CTR.")
            ),
            "relatorio_coo_operacoes": "Operação ociosa para este SKU.",
            "plano_acao_shopee": [
                "1. TÍTULO: Reescreva incluindo palavras-chave exatas da busca.",
                "2. FOTO: Troque a capa por uma imagem do item em uso.",
                "3. IMPULSO: Inscreva em Campanhas Shopee gratuitas.",
                "4. VALIDAÇÃO: Ative R$ 3,00 em 'Busca por Descoberta' só para testar impressões."
            ],
            "analise_de_consequencias": "Melhorar o SEO e a foto tirará o produto da invisibilidade para gerar os primeiros cliques.",
            "dados_atuais": original,
            "score_urgencia": 0,
            "dias_estoque": calcular_dias_estoque(original)
        })
    return resultados


def _resultado_deterministico_local(p: dict, var: dict, original: dict) -> dict:
    """Parecer local para SKU de evidência baixa e sem urgência (modo econômico).

    Racional: o atuador bloqueia execução automática para evidência baixa, ou
    seja, uma análise de IA nesses SKUs produz apenas narrativa não executável.
    A camada determinística cobre os mesmos campos a custo zero; o SKU volta à
    fila de IA assim que a evidência subir ou o score de urgência passar de 40.
    """
    recomendacao = original.get("recomendacao_executiva", "Monitorar e coletar mais evidência.")
    return {
        "item_id": p["item_id"],
        "model_id": var["model_id"],
        "tipo_acao": "MANTER",
        "novo_preco_sugerido": var["preco_atual"],
        "horas_duracao_promocao": 0,
        "previsao_vendas_7d": var.get("previsao_deterministica_vendas_7d", 0),
        "previsao_lucro_7d": var.get("previsao_deterministica_lucro_7d", 0.0),
        "previsao_vendas_30d": var.get("previsao_deterministica_vendas_30d", 0),
        "previsao_lucro_30d": var.get("previsao_deterministica_lucro_30d", 0.0),
        "plano_curto_prazo_7d": [
            "Coletar exportações diárias (tráfego e ads) para elevar a cobertura de evidência.",
            recomendacao,
        ],
        "plano_longo_prazo_30d": ["Reavaliar com IA quando a evidência sair de 'Baixa' ou surgir urgência."],
        "elasticidade_preco_volume": var.get("elasticidade_preco_volume", 0),
        "cluster_mercado": original.get("cluster_mercado", "Estável"),
        "recomendacao_executiva": recomendacao,
        "relatorio_cfo_financas": "Análise local (modo econômico): evidência baixa; a projeção determinística é o cenário base.",
        "relatorio_cmo_marketing": str(var.get("limite_evidencia") or "Amostra curta ou pouco tráfego."),
        "relatorio_coo_operacoes": "Sem pressão operacional detectada pelas regras determinísticas.",
        "analise_de_consequencias": "Nenhuma intervenção automática; o SKU volta à análise de IA se a evidência ou a urgência mudarem.",
        "analise_local": True,
        "falha_modelo_externo": False,
        "dados_atuais": original,
        "score_urgencia": calcular_score_urgencia(original),
        "dias_estoque": calcular_dias_estoque(original),
    }


def _dividir_lote(lote: list[dict]) -> tuple[list[dict], list[dict]]:
    """Divide um lote em dois preservando o contexto do produto pai."""
    if len(lote) > 1:
        meio = len(lote) // 2
        return lote[:meio], lote[meio:]
    unico = lote[0]
    vars_ = unico["variacoes_ativas"]
    meio = max(1, len(vars_) // 2)
    return (
        [{**unico, "variacoes_ativas": vars_[:meio]}],
        [{**unico, "variacoes_ativas": vars_[meio:]}],
    )


def _executar_lote_adaptativo(
    lote: list[dict], horizonte: str, telemetria: dict | None, profundidade: int = 0,
) -> list[dict]:
    """Executa um lote; se falhar inteiro (timeout/truncamento), divide e reenvia.

    Timeout e truncamento são quase sempre função do tamanho do payload:
    dividir isola o problema com custo total próximo ao da tentativa única,
    convertendo uma falha dura em duas requisições menores que cabem no
    orçamento de tokens e no tempo de resposta.
    """
    resultado = chamar_cerebro_openai_preditivo(lote, horizonte, telemetria=telemetria)
    total_vars = sum(len(p.get("variacoes_ativas", [])) for p in lote)
    lote_falhou = bool(resultado) and all(r.get("falha_modelo_externo") for r in resultado)
    if lote_falhou and total_vars > 1 and profundidade < 2:
        logger.warning(
            f"Lote com {total_vars} SKUs falhou; dividindo para reduzir o payload (nível {profundidade + 1})."
        )
        if telemetria is not None:
            telemetria["lotes_divididos"] = telemetria.get("lotes_divididos", 0) + 1
        metade_a, metade_b = _dividir_lote(lote)
        return (
            _executar_lote_adaptativo(metade_a, horizonte, telemetria, profundidade + 1)
            + _executar_lote_adaptativo(metade_b, horizonte, telemetria, profundidade + 1)
        )
    return resultado


def _fatiar_em_lotes(produtos_ativos: list[dict], max_vars_por_lote: int) -> list[list[dict]]:
    """Smart batching: fatia variações mantendo o contexto do produto pai."""
    lotes = []
    lote_atual = []
    variacoes_no_lote = 0
    for p in produtos_ativos:
        vars_ativas = p["variacoes_ativas"]
        for i in range(0, len(vars_ativas), max_vars_por_lote):
            chunk_vars = vars_ativas[i: i + max_vars_por_lote]
            p_chunk = {
                "item_id": p["item_id"],
                "nome_produto": p["nome_produto"],
                "metricas_macro_produto_30_dias": p["metricas_macro_produto_30_dias"],
                "sinais_produto": p.get("sinais_produto", {}),
                "variacoes_ativas": chunk_vars
            }
            if lote_atual and variacoes_no_lote + len(chunk_vars) > max_vars_por_lote:
                lotes.append(lote_atual)
                lote_atual = []
                variacoes_no_lote = 0
            lote_atual.append(p_chunk)
            variacoes_no_lote += len(chunk_vars)
    if lote_atual:
        lotes.append(lote_atual)
    return lotes


def processar_em_lotes(
    dossie_completo: list[dict], horizonte: str, ao_concluir_lote=None,
    modo_economico: bool = True, telemetria: dict | None = None,
    ao_progresso=None,
) -> list[dict]:
    """Pipeline de análise de um horizonte:
    gatekeeper local → modo econômico → lotes adaptativos → OpenAI.

    Nenhuma exceção de lote aborta a auditoria: lotes irrecuperáveis viram
    fallback marcado (falha_modelo_externo) e são reanalisados na retomada.

    ao_progresso(fracao: float, texto: str) é opcional: a UI injeta a barra de
    progresso; sem callback, o módulo roda igualmente (CLI, testes, página 4).
    """
    config.horizonte_em_dias(horizonte)  # valida o horizonte
    max_vars_por_lote = 5 if horizonte == "7d" else 2
    originais_por_chave = {
        (int(d["item_id"]), int(d["model_id"])): d
        for d in dossie_completo
        if d.get("item_id") is not None and d.get("model_id") is not None
    }

    # 1. Agrupar variações por produto pai
    produtos_agrupados = _agrupar_por_produto(dossie_completo)

    # 2. O GATEKEEPER: separa os vivos dos fantasmas (processamento gratuito)
    produtos_ativos = []
    resultados_finais = []

    for p in produtos_agrupados.values():
        macro = p["metricas_macro_produto_30_dias"]
        vendas_totais_30d = sum(v["vendas_30d_reais"] for v in p["variacoes_ativas"])
        topo_mensuravel = any(
            v.get("funil_organico_impressoes_30d") is not None
            for v in p["variacoes_ativas"]
        )
        cobertura_trafego = int(macro.get("dias_trafego_coletados_30d", 0) or 0)
        evidencia_descoberta = cobertura_trafego >= 7 or topo_mensuravel

        if (
            evidencia_descoberta
            and macro["visitas_totais_30d"] <= 10
            and macro["gasto_ads_total_30d"] == 0
            and vendas_totais_30d == 0
        ):
            resultados_finais.extend(_resolver_fantasma_local(p, originais_por_chave))
        else:
            produtos_ativos.append(p)

    # 2b. MODO ECONÔMICO: SKUs de evidência baixa e sem urgência (score < 40)
    #     recebem parecer determinístico local. Urgência alta sempre vai à IA.
    skus_analise_local = 0
    if modo_economico:
        produtos_para_ia = []
        for p in produtos_ativos:
            variacoes_ia = []
            for var in p["variacoes_ativas"]:
                original = originais_por_chave.get((int(p["item_id"]), int(var["model_id"])))
                if (
                    original is not None
                    and var.get("qualidade_evidencia") == "Baixa"
                    and calcular_score_urgencia(original) < 40
                ):
                    resultados_finais.append(_resultado_deterministico_local(p, var, original))
                    skus_analise_local += 1
                else:
                    variacoes_ia.append(var)
            if variacoes_ia:
                produtos_para_ia.append({**p, "variacoes_ativas": variacoes_ia})
        produtos_ativos = produtos_para_ia
        if skus_analise_local:
            logger.info(f"💸 Modo econômico: {skus_analise_local} SKU(s) resolvidos localmente sem custo de IA.")
            if telemetria is not None:
                telemetria["skus_analise_local"] = telemetria.get("skus_analise_local", 0) + skus_analise_local

    produtos_ativos = sorted(produtos_ativos, key=lambda x: x["score_urgencia_maximo"], reverse=True)

    if resultados_finais and ao_concluir_lote:
        ao_concluir_lote(list(resultados_finais))

    # 3. SMART BATCHING e chamadas sequenciais (evita rate limit e custo duplicado)
    lotes = _fatiar_em_lotes(produtos_ativos, max_vars_por_lote)

    def _notificar_progresso(fracao: float, texto: str) -> None:
        if ao_progresso is None:
            return
        try:
            ao_progresso(min(1.0, max(0.0, fracao)), texto)
        except Exception as exc:
            logger.debug(f"Callback de progresso falhou (ignorado): {exc}")

    if lotes:
        _notificar_progresso(0.0, "🚀 Iniciando auditoria C-Level por API OpenAI...")
        lotes_concluidos = 0

        for lote in lotes:
            try:
                resultado_lote = _executar_lote_adaptativo(lote, horizonte, telemetria)
            except Exception as e:
                # Uma falha inesperada não pode abortar a auditoria inteira:
                # o lote vira fallback marcado e será reanalisado na retomada.
                logger.error(f"Erro inesperado no lote; aplicando fallback local: {e}")
                resultado_lote = gerar_fallback_lote(lote, horizonte, f"Erro interno no lote: {e}")

            resultados_do_lote = []
            for rec in resultado_lote:
                try:
                    rec_item_id = int(rec.get("item_id"))
                    rec_model_id = int(rec.get("model_id"))
                except (TypeError, ValueError):
                    continue

                original = originais_por_chave.get((rec_item_id, rec_model_id))
                if not original:
                    continue

                rec = normalizar_saida_modelo(rec, original)
                rec["item_id"] = rec_item_id
                rec["model_id"] = rec_model_id
                rec["horizonte_auditoria"] = horizonte
                rec["dados_atuais"] = original
                rec["score_urgencia"] = calcular_score_urgencia(original)
                rec["dias_estoque"] = calcular_dias_estoque(original)

                preco_original = float(original.get("preco_atual", 0) or 0)
                if rec.get("novo_preco_sugerido") is None:
                    rec["novo_preco_sugerido"] = preco_original

                rec.setdefault("previsao_vendas_7d", original.get("previsao_vendas_7d", 0))
                rec.setdefault("previsao_lucro_7d", original.get("previsao_lucro_7d", 0))
                rec.setdefault("previsao_vendas_30d", original.get("previsao_vendas_30d", 0))
                rec.setdefault("previsao_lucro_30d", original.get("previsao_lucro_30d", 0))
                rec.setdefault("plano_curto_prazo_7d", [])
                rec.setdefault("plano_longo_prazo_30d", [])
                rec.setdefault("elasticidade_preco_volume", original.get("elasticidade_preco_volume", 0))
                rec.setdefault("cluster_mercado", original.get("cluster_mercado", "Estável"))
                rec.setdefault("recomendacao_executiva", original.get("recomendacao_executiva", "Monitorar"))
                resultados_finais.append(rec)
                resultados_do_lote.append(rec)

            if resultados_do_lote and ao_concluir_lote:
                ao_concluir_lote(resultados_do_lote)

            lotes_concluidos += 1
            _notificar_progresso(
                lotes_concluidos / len(lotes),
                f"⏳ Conselho auditando {lotes_concluidos}/{len(lotes)} submódulos ativos..."
            )

    return resultados_finais
