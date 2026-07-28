"""
estudio_shopee/gerador_anuncio.py
==================================
Cliente OpenAI REST direto (sem SDK) para a geração do anúncio completo do
Estúdio: título, descrição e palavras-chave, a partir da imagem final do
produto — uma chamada de chat completions com mensagem MULTIMODAL (texto +
imagem em data URI base64) e resposta em JSON mode.

Mesmo padrão já usado no app principal em
`Local_AI/analista_dados_shopee/cerebro/config.py` / `cerebro/motor_ia.py`:
sessão `requests` reaproveitada, `response_format={"type": "json_object"}`,
parsing defensivo da resposta e exceções próprias e claras em vez de deixar
tracebacks crus de `requests`/`json` subirem. Este módulo NÃO importa
`streamlit` — precisa continuar testável de forma isolada (T-005), fora de
um app Streamlit rodando.

A parte de plumbing (`ErroGeracaoAnuncio`, `chamar_openai_visao`) foi feita em
T-001. Este módulo também expõe `construir_data_uri` (usada tanto pela
edição de imagem em `app.py` quanto pelo anúncio aqui — existe em um único
lugar) e, a partir de T-002, `gerar_anuncio_shopee`: a função que de fato
monta o prompt de copywriting, a mensagem multimodal (texto + imagem) e
valida a resposta da IA.
"""

import base64
import json
import os
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from dotenv import load_dotenv


class ErroGeracaoAnuncio(Exception):
    """Erro claro em qualquer etapa da geração do anúncio via IA: credencial
    ausente, falha de rede, resposta HTTP de erro ou conteúdo que não é um
    JSON válido. Quem chama `chamar_openai_visao` nunca precisa lidar com
    exceções cruas de `requests`/`json` — só com esta, com mensagem já
    pronta para exibir na UI (RF-07 da ESPECIFICACAO.md: falha não derruba a
    aba do Estúdio)."""


# ── Configuração ──────────────────────────────────────────────────────────
# Carrega as MESMAS variáveis de Local_AI/CHAVES.env que o Estúdio já usa
# (ver app.py). Não depende de app.py já ter rodado load_dotenv: este módulo
# carrega suas próprias variáveis para funcionar mesmo importado
# isoladamente (ex.: em teste), sem precisar de um app Streamlit no ar.
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent  # Local_AI/

load_dotenv(dotenv_path=ROOT_DIR / "CHAVES.env")

OPENAI_API_BASE_URL = (os.getenv("OPENAI_API_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
OPENAI_CHAT_COMPLETIONS_URL = (
    OPENAI_API_BASE_URL
    if OPENAI_API_BASE_URL.endswith("/chat/completions")
    else f"{OPENAI_API_BASE_URL}/chat/completions"
)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL_ANUNCIO = (os.getenv("OPENAI_MODEL_ANUNCIO") or "gpt-5.6-luna").strip()

HTTP_SESSION = requests.Session()
HTTP_SESSION.mount("http://", HTTPAdapter(pool_connections=2, pool_maxsize=4, max_retries=0))
HTTP_SESSION.mount("https://", HTTPAdapter(pool_connections=2, pool_maxsize=4, max_retries=0))


def _validar_credencial() -> None:
    """Falha cedo e com mensagem clara — antes de qualquer chamada de rede —
    quando a credencial não está configurada."""
    if not OPENAI_API_KEY:
        raise ErroGeracaoAnuncio(
            "OPENAI_API_KEY não configurada. Adicione a chave em "
            "Local_AI/CHAVES.env (veja Local_AI/CHAVES.env.example) e "
            "reinicie o Estúdio."
        )


def chamar_openai_visao(mensagens: list[dict], timeout: int = 60) -> dict:
    """Chama a API OpenAI Chat Completions em JSON mode com suporte a
    mensagens multimodais (texto + imagem) e devolve o JSON já decodificado
    do campo `choices[0].message.content` da resposta.

    `mensagens` segue o formato nativo da API OpenAI: lista de dicts
    `{"role": ..., "content": ...}`, onde `content` pode ser uma string ou
    uma lista de blocos `{"type": "text", "text": ...}` /
    `{"type": "image_url", "image_url": {"url": "data:image/...;base64,..."}}`.

    Nunca deixa subir uma exceção crua de `requests` ou `json`: qualquer
    falha (credencial ausente, rede, HTTP >= 400, conteúdo que não é JSON
    válido) vira `ErroGeracaoAnuncio` com mensagem clara e, quando aplicável,
    a causa original anexada (`raise ... from e`).
    """
    _validar_credencial()

    payload = {
        "model": OPENAI_MODEL_ANUNCIO,
        "messages": mensagens,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = HTTP_SESSION.post(
            OPENAI_CHAT_COMPLETIONS_URL,
            headers=headers,
            json=payload,
            timeout=timeout,
        )
    except requests.exceptions.Timeout as e:
        raise ErroGeracaoAnuncio(
            f"A API OpenAI não respondeu em {timeout}s (timeout)."
        ) from e
    except requests.exceptions.RequestException as e:
        raise ErroGeracaoAnuncio(f"Falha de rede ao chamar a API OpenAI: {e}") from e

    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise ErroGeracaoAnuncio(
            f"API OpenAI retornou erro {response.status_code}: {response.text[:500]}"
        ) from e

    try:
        corpo_resposta = response.json()
        mensagem = corpo_resposta["choices"][0]["message"]
        conteudo = mensagem["content"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise ErroGeracaoAnuncio(
            f"Resposta da API OpenAI em formato inesperado: {e}"
        ) from e

    if conteudo is None:
        # A API OpenAI retorna `message.content = null` quando o modelo
        # recusa a resposta por política de moderação/segurança — nesse
        # caso o motivo costuma vir em `message.refusal`. Plausível aqui
        # porque este módulo lida com imagens de produto (visão).
        recusa = mensagem.get("refusal") if isinstance(mensagem, dict) else None
        if recusa:
            raise ErroGeracaoAnuncio(f"A IA recusou gerar o anúncio: {recusa}")
        raise ErroGeracaoAnuncio(
            "A IA não devolveu conteúdo (content nulo), possivelmente por "
            "recusa de moderação/segurança sem motivo detalhado."
        )

    try:
        resultado = json.loads(conteudo)
    except (json.JSONDecodeError, TypeError) as e:
        raise ErroGeracaoAnuncio(f"A IA não devolveu um JSON válido: {e}") from e

    if not isinstance(resultado, dict):
        raise ErroGeracaoAnuncio(
            "A IA devolveu um JSON válido, mas não é um objeto "
            f"(tipo recebido: {type(resultado).__name__})."
        )

    return resultado


# ── Data URI (compartilhado com app.py — não duplicar) ──────────────────────

def construir_data_uri(imagem_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    """Codifica bytes de imagem em uma data URI base64 (`data:{mime};base64,...`).

    Mesma função antes duplicada em `app.py` (edição de imagem via fal.ai) e
    usada aqui para a mensagem multimodal do anúncio — existe em um único
    lugar agora; `app.py` importa esta implementação."""
    img_b64 = base64.b64encode(imagem_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{img_b64}"


# ── Geração do anúncio (T-002) ───────────────────────────────────────────────

PROMPT_SISTEMA_ANUNCIO = """Você é um copywriter especialista em anúncios de e-commerce para a Shopee Brasil, especializado em produtos de impressão 3D sob demanda.

Sua tarefa: a partir de UMA imagem do produto (a foto final que será usada como capa do anúncio) e de um contexto textual fornecido pelo vendedor, escrever o TÍTULO, a DESCRIÇÃO e uma lista de PALAVRAS-CHAVE do anúncio.

REGRA MAIS IMPORTANTE — NUNCA INVENTE:
Baseie-se SOMENTE (1) no que é VISUALMENTE OBSERVÁVEL na imagem enviada — o produto em si, cor/material aparente, formato, cenário/fundo, ângulo, estilo de composição (fundo branco de catálogo, cena de ambiente, ou produto sendo segurado por uma mão) — e (2) no contexto textual fornecido pelo vendedor (nome/descrição do produto, cor/material declarado, estilo escolhido, cenário descrito). NUNCA invente especificações técnicas que não estejam visíveis na foto nem informadas no contexto (ex.: dimensões exatas, peso, resistência mecânica, compatibilidade com outros produtos, garantia, marca, certificações). Se uma informação não é possível ver na imagem nem foi informada no contexto, simplesmente NÃO a mencione — não preencha a lacuna com um "chute" plausível.

REGRAS DO TÍTULO:
- Combine termos de busca prováveis (que um comprador da Shopee digitaria para encontrar este produto) com um gatilho de venda real e verificável pela imagem/contexto — nunca clickbait enganoso ("o melhor do Brasil", "imperdível", promessas vagas e vazias).
- Comprimento alvo: por volta de 120 a 150 caracteres (o limite técnico da Shopee é de ~256 caracteres, mas o título deve ficar BEM abaixo desse limite).
- Evite excesso de emojis e símbolos especiais no título (a Shopee pode rejeitar ou penalizar títulos assim); no máximo 1 emoji, e só se fizer sentido para o produto.

REGRAS DA DESCRIÇÃO:
- Estruture em blocos, nesta ordem: (1) abertura chamativa e curta que já entrega o principal benefício observável; (2) bullets com benefícios e diferenciais reais, baseados apenas no que é visível na foto ou foi informado no contexto; (3) especificações visíveis (cor/material aparente, formato, acabamento) — nunca specs que não são visíveis nem foram informadas; (4) uma chamada para ação final, incentivando a compra.
- Seja objetivo e direto: BEM abaixo do limite de ~5.000 caracteres da Shopee — normalmente alguns parágrafos curtos e bullets bastam, sem enrolação.

REGRAS DAS PALAVRAS-CHAVE:
- Liste termos de busca relevantes e prováveis para este produto, curtos (1 a 4 palavras cada), sem repetir o título inteiro como se fosse uma palavra-chave só.

IDIOMA: responda inteiramente em português do Brasil — este anúncio é para o comprador brasileiro da Shopee (diferente de eventuais instruções de edição de imagem em inglês, que são para outro motor e não fazem parte desta tarefa).

FORMATO DE SAÍDA: responda SOMENTE com um objeto JSON válido, sem markdown, sem comentários, sem texto fora do JSON, com exatamente estas três chaves:
{"titulo": "string", "descricao": "string", "palavras_chave": ["string", "string", ...]}"""


def _montar_texto_contexto_produto(contexto_produto: dict, historico_estilo: str) -> str:
    """Monta o bloco de texto (contexto do vendedor) que acompanha a imagem na
    mensagem multimodal. Todas as chaves de `contexto_produto` são opcionais —
    quanto mais preenchidas, mais fiel o anúncio gerado fica ao produto real."""
    partes = [
        "Gere o anúncio para o produto mostrado na imagem enviada, combinando "
        "o que você observar na foto com o contexto textual informado pelo "
        "vendedor abaixo (quando houver)."
    ]

    nome = str(contexto_produto.get("produto") or contexto_produto.get("nome") or "").strip()
    if nome:
        partes.append(f"- Nome/descrição curta do produto (informado pelo vendedor): {nome}")

    produtos_formatados = str(contexto_produto.get("produtos_formatados") or "").strip()
    if produtos_formatados:
        partes.append(
            "- Detalhamento por posição/slot informado pelo vendedor (pode conter "
            f"mais de um item na mesma foto):\n{produtos_formatados}"
        )

    cor = str(contexto_produto.get("cor") or contexto_produto.get("material") or "").strip()
    if cor:
        partes.append(f"- Cor/material declarado pelo vendedor: {cor}")

    estilo = str(contexto_produto.get("estilo") or "").strip()
    if estilo:
        partes.append(f"- Estilo/cenário de composição escolhido pelo vendedor: {estilo}")

    cenario = str(contexto_produto.get("instrucao") or contexto_produto.get("cenario") or "").strip()
    if cenario:
        partes.append(f"- Descrição do cenário/uso pretendido (informado pelo vendedor): {cenario}")

    if not any([nome, produtos_formatados, cor, estilo, cenario]):
        partes.append(
            "- O vendedor não informou nenhum contexto textual adicional além "
            "da imagem: baseie-se SOMENTE no que está visível na foto."
        )

    if historico_estilo and historico_estilo.strip():
        partes.append(
            "\n[REFERÊNCIA DE ESTILO — anúncios já aprovados anteriormente pelo "
            "vendedor, usados APENAS como exemplo de tom de voz e estrutura de "
            "texto; NUNCA copie produto, cor, material ou qualquer especificação "
            "destes exemplos, eles são de OUTROS produtos]\n"
            f"{historico_estilo.strip()}"
        )

    return "\n".join(partes)


def _construir_mensagens_anuncio(
    imagem_bytes: bytes, contexto_produto: dict, historico_estilo: str
) -> list[dict]:
    """Monta a mensagem multimodal (texto + imagem em data URI) enviada a
    `chamar_openai_visao` para gerar o anúncio."""
    data_uri = construir_data_uri(imagem_bytes)
    texto_contexto = _montar_texto_contexto_produto(contexto_produto, historico_estilo)
    return [
        {"role": "system", "content": PROMPT_SISTEMA_ANUNCIO},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": texto_contexto},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ],
        },
    ]


def _validar_resposta_anuncio(resultado: dict) -> dict:
    """Garante que a resposta da IA tem exatamente `titulo` (str não vazia),
    `descricao` (str não vazia) e `palavras_chave` (list[str] não vazia) —
    nunca deixa a função devolver um dict incompleto ou malformado
    silenciosamente. Qualquer desvio do schema levanta `ErroGeracaoAnuncio`
    com mensagem clara sobre o que veio errado."""
    titulo = resultado.get("titulo")
    if not isinstance(titulo, str) or not titulo.strip():
        raise ErroGeracaoAnuncio(
            "A IA não devolveu um 'titulo' válido (esperado: string não "
            f"vazia; recebido: {'ausente' if titulo is None else type(titulo).__name__})."
        )

    descricao = resultado.get("descricao")
    if not isinstance(descricao, str) or not descricao.strip():
        raise ErroGeracaoAnuncio(
            "A IA não devolveu uma 'descricao' válida (esperado: string não "
            f"vazia; recebido: {'ausente' if descricao is None else type(descricao).__name__})."
        )

    palavras_chave = resultado.get("palavras_chave")
    if not isinstance(palavras_chave, list) or not palavras_chave:
        raise ErroGeracaoAnuncio(
            "A IA não devolveu 'palavras_chave' válidas (esperado: lista de "
            "strings não vazia; recebido: "
            f"{'ausente' if palavras_chave is None else type(palavras_chave).__name__})."
        )
    if not all(isinstance(item, str) and item.strip() for item in palavras_chave):
        raise ErroGeracaoAnuncio(
            "A IA devolveu 'palavras_chave' com item inválido (esperado: "
            "todos os itens da lista devem ser strings não vazias)."
        )

    return {
        "titulo": titulo.strip(),
        "descricao": descricao.strip(),
        "palavras_chave": [item.strip() for item in palavras_chave],
    }


def gerar_anuncio_shopee(
    imagem_bytes: bytes, contexto_produto: dict, historico_estilo: str = ""
) -> dict:
    """Gera o anúncio completo da Shopee (título + descrição + palavras-chave)
    a partir da imagem final do produto e do contexto textual fornecido,
    usando `chamar_openai_visao` (T-001) com o prompt de copywriting de venda
    definido em `PROMPT_SISTEMA_ANUNCIO`.

    `contexto_produto` aceita, entre outras chaves, `produto`/`nome`,
    `cor`/`material`, `estilo`, `instrucao`/`cenario` e `produtos_formatados`
    — os mesmos campos já reunidos em `st.session_state.dados_atual` no
    `app.py` (não precisa ser exatamente essa struct, só os mesmos campos de
    conteúdo). Todas as chaves são opcionais, mas quanto mais contexto real
    for passado, mais fiel o texto gerado fica ao produto de verdade.

    `historico_estilo` é opcional: texto livre com anúncios já aprovados pelo
    vendedor, usado só como referência de tom/estrutura (nunca de conteúdo —
    ver instrução explícita no prompt de sistema).

    Retorna sempre um dict com exatamente `titulo` (str), `descricao` (str) e
    `palavras_chave` (list[str]) — nunca um dict incompleto ou malformado:
    qualquer desvio do schema esperado na resposta da IA levanta
    `ErroGeracaoAnuncio` com mensagem clara."""
    if not imagem_bytes:
        raise ErroGeracaoAnuncio(
            "Nenhuma imagem foi fornecida para gerar o anúncio — é preciso a "
            "imagem final do produto para o modelo de visão descrever o que "
            "está vendo."
        )

    mensagens = _construir_mensagens_anuncio(
        imagem_bytes, contexto_produto or {}, historico_estilo or ""
    )
    resultado = chamar_openai_visao(mensagens)
    return _validar_resposta_anuncio(resultado)
