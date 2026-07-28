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

Este arquivo é só a INFRAESTRUTURA da chamada (T-001: plumbing). A
construção do prompt e das mensagens específicas do anúncio — a partir do
contexto real do produto e da imagem enviada — é objeto de T-002.
"""

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
