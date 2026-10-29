"""
cerebro/provedor_ia.py
======================
Quem responde às análises do Cérebro (página 3) e ao Chat (página 4).

  - "claude_code": o SEU plano Claude (Pro/Max), pelo Claude Code instalado
    nesta máquina (`claude -p`). Nenhuma chave de API é usada: o processo é
    iniciado SEM ANTHROPIC_API_KEY no ambiente, então o CLI só consegue usar o
    login claude.ai do plano e nunca cai em cobrança por uso. O consumo entra
    no limite do plano (janela de 5 horas e semanal), o mesmo do Claude Code
    usado no terminal.
  - "openai": API da OpenAI, paga por token (comportamento original).

A escolha e os modelos ficam no CHAVES_DADOS.env (IA_PROVEDOR e CLAUDE_*),
editáveis na tela pelo painel ⚙️ Motor de IA (utils/painel_ia.py). Tudo é
lido do ambiente a cada chamada: salvar na tela vale na hora, sem reiniciar.

Sem Streamlit: o mesmo módulo roda no app, em CLI e nos testes.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import set_key

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / "CHAVES_DADOS.env"

PROVEDORES = {
    "claude_code": "Claude — seu plano (Claude Code)",
    "openai": "OpenAI — API paga por uso",
}
MODELOS_CLAUDE = {
    "sonnet": "Sonnet — recomendado: preciso e econômico no limite do plano",
    "opus": "Opus — pareceres mais profundos, consome o limite bem mais rápido",
    "haiku": "Haiku — rápido e leve, para triagem",
}
ESFORCOS = {"low": "Baixo", "medium": "Médio", "high": "Alto"}
USOS = {"7d": "Análise de 7 dias", "30d": "Diagnóstico de 30 dias", "chat": "Chat"}

# Padrões pensados para o plano Pro não estourar numa auditoria: Sonnet em
# todos os usos e raciocínio alto só no diagnóstico mensal.
PADROES = {
    "IA_PROVEDOR": "openai",
    "CLAUDE_MODEL_7D": "sonnet",
    "CLAUDE_EFFORT_7D": "medium",
    "CLAUDE_MODEL_30D": "sonnet",
    "CLAUDE_EFFORT_30D": "high",
    "CLAUDE_MODEL_CHAT": "sonnet",
    "CLAUDE_EFFORT_CHAT": "low",
    "CLAUDE_MAX_CHAMADAS_AUDITORIA": "25",
    "CLAUDE_EXECUTAVEL": "claude",
}

# Variáveis que fariam o CLI cobrar por uso (chave de API) ou sair do plano
# (Bedrock/Vertex/Foundry): nunca chegam ao processo do Claude Code.
_VARIAVEIS_FORA_DO_PLANO = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
)
_SINAIS_DE_LIMITE = (
    "usage limit", "limit reached", "rate limit", "rate_limit", "hit your limit",
    "5-hour limit", "weekly limit", "limite de uso",
)


class ErroProvedorIA(RuntimeError):
    """O modelo não respondeu (login, rede, resposta inválida)."""


class TempoEsgotadoIA(ErroProvedorIA):
    """O modelo não respondeu no tempo limite (não vale repetir o mesmo lote)."""


class LimiteDoPlanoAtingido(ErroProvedorIA):
    """O limite de uso do plano Claude acabou: repetir agora só gastaria tempo."""


@dataclass(frozen=True)
class RespostaIA:
    texto: str
    tokens_entrada: int
    tokens_saida: int
    modelo: str


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURAÇÃO
# ══════════════════════════════════════════════════════════════════════════════

def _valor(chave: str) -> str:
    return (os.getenv(chave) or "").strip() or PADROES[chave]


def provedor() -> str:
    escolhido = _valor("IA_PROVEDOR").lower()
    return escolhido if escolhido in PROVEDORES else "openai"


def usando_claude() -> bool:
    return provedor() == "claude_code"


def modelo_claude(uso: str) -> str:
    """Apelido (sonnet/opus/haiku) ou nome completo (claude-...) do modelo do uso."""
    chave = f"CLAUDE_MODEL_{uso.upper()}"
    modelo = _valor(chave).lower()
    return modelo if modelo in MODELOS_CLAUDE or modelo.startswith("claude-") else PADROES[chave]


def esforco_claude(uso: str) -> str:
    chave = f"CLAUDE_EFFORT_{uso.upper()}"
    esforco = _valor(chave).lower()
    return esforco if esforco in ESFORCOS else PADROES[chave]


def max_chamadas_auditoria() -> int:
    try:
        return max(1, int(_valor("CLAUDE_MAX_CHAMADAS_AUDITORIA")))
    except ValueError:
        return int(PADROES["CLAUDE_MAX_CHAMADAS_AUDITORIA"])


def descricao_modelo(uso: str) -> str:
    """Texto curto para a tela: quem responde e com que modelo."""
    if usando_claude():
        return (
            f"Claude {modelo_claude(uso).capitalize()} "
            f"(raciocínio {ESFORCOS[esforco_claude(uso)].lower()}, seu plano)"
        )
    from cerebro import config  # import tardio: config só chama este módulo sob demanda
    modelo = {"7d": config.OPENAI_MODEL_7D, "30d": config.OPENAI_MODEL_30D}.get(uso, config.OPENAI_MODEL_CHAT)
    return f"OpenAI {modelo} (API paga)"


def salvar_configuracao(valores: dict) -> None:
    """Grava no CHAVES_DADOS.env e aplica no processo na hora."""
    for chave, valor in valores.items():
        if chave not in PADROES:
            raise ValueError(f"Configuração desconhecida: {chave}")
        set_key(str(ENV_FILE), chave, str(valor), quote_mode="never")
        os.environ[chave] = str(valor)
    limpar_status()


# ══════════════════════════════════════════════════════════════════════════════
# CLAUDE CODE (plano)
# ══════════════════════════════════════════════════════════════════════════════

def _executavel() -> str | None:
    return shutil.which(_valor("CLAUDE_EXECUTAVEL"))


def _ambiente_do_plano() -> dict:
    """Ambiente sem credenciais de API: o CLI só consegue usar o login do plano."""
    return {k: v for k, v in os.environ.items() if k not in _VARIAVEIS_FORA_DO_PLANO}


def _sem_janela() -> dict:
    # No Windows, sem isto cada chamada abriria uma janela de console piscando.
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


_cache_status: dict = {}


def limpar_status() -> None:
    _cache_status.clear()


def status_claude_code(forcar: bool = False) -> dict:
    """Login do Claude Code: {"ok", "mensagem", "plano", "email"}, com cache de 60 s."""
    if not forcar and _cache_status and time.monotonic() - _cache_status["em"] < 60:
        return _cache_status["status"]
    status = _consultar_status()
    _cache_status.update(em=time.monotonic(), status=status)
    return status


def _consultar_status() -> dict:
    executavel = _executavel()
    if not executavel:
        return {
            "ok": False, "plano": None, "email": None,
            "mensagem": (
                "Claude Code não encontrado neste computador. Instale com "
                "`npm install -g @anthropic-ai/claude-code` e faça login rodando `claude` no terminal."
            ),
        }
    try:
        proc = subprocess.run(
            [executavel, "auth", "status"], capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=_ambiente_do_plano(), timeout=45, **_sem_janela(),
        )
        dados = json.loads(proc.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return {"ok": False, "plano": None, "email": None,
                "mensagem": f"Não consegui consultar o login do Claude Code: {exc}"}

    plano, email = dados.get("subscriptionType"), dados.get("email")
    if not dados.get("loggedIn"):
        return {"ok": False, "plano": plano, "email": email,
                "mensagem": "O Claude Code não está logado. Rode `claude` no terminal e entre com a conta do seu plano."}
    if dados.get("authMethod") != "claude.ai":
        return {
            "ok": False, "plano": plano, "email": email,
            "mensagem": (
                f"O Claude Code está autenticado por '{dados.get('authMethod')}', não pelo plano claude.ai — "
                "isso cobraria por uso. Rode `claude auth login` e entre com a conta do plano."
            ),
        }
    nome_plano = str(plano or "Claude").capitalize()
    return {"ok": True, "plano": plano, "email": email,
            "mensagem": f"Conectado ao plano {nome_plano} ({email})."}


def chamar_claude(sistema: str, mensagem: str, *, uso: str, timeout: int = 600) -> RespostaIA:
    """Uma pergunta ao Claude pelo plano.

    Levanta LimiteDoPlanoAtingido (limite do plano), TempoEsgotadoIA ou
    ErroProvedorIA (login, execução, resposta inválida).
    """
    executavel = _executavel()
    if not executavel:
        raise ErroProvedorIA("Claude Code não encontrado neste computador.")
    modelo, esforco = modelo_claude(uso), esforco_claude(uso)

    with tempfile.TemporaryDirectory(prefix="cerebro_claude_") as pasta:
        # Prompt de sistema por ARQUIVO e mensagem por stdin: no Windows o
        # atalho claude.cmd corta linhas de comando acima de 8.191 caracteres.
        arquivo_sistema = Path(pasta) / "sistema.txt"
        arquivo_sistema.write_text(sistema, encoding="utf-8")
        comando = [
            executavel, "-p",
            "--output-format", "json",
            "--model", modelo,
            "--effort", esforco,
            "--tools", "",               # só responde: sem ler arquivos nem rodar comandos
            "--safe-mode",               # ignora CLAUDE.md, memória, plugins e hooks da máquina
            "--no-session-persistence",  # não polui o histórico de sessões do Claude Code
            "--system-prompt-file", str(arquivo_sistema),
        ]
        try:
            proc = subprocess.run(
                comando, input=mensagem, cwd=pasta, capture_output=True, text=True,
                encoding="utf-8", errors="replace", env=_ambiente_do_plano(),
                timeout=timeout, **_sem_janela(),
            )
        except subprocess.TimeoutExpired as exc:
            raise TempoEsgotadoIA(f"O Claude não respondeu em {timeout // 60} minuto(s).") from exc
        except OSError as exc:
            raise ErroProvedorIA(f"Não consegui executar o Claude Code: {exc}") from exc

    try:
        dados = json.loads(proc.stdout)
    except ValueError:
        raise _erro_da_saida((proc.stderr or proc.stdout or "").strip()) from None
    texto = str(dados.get("result") or "").strip()
    if proc.returncode != 0 or dados.get("is_error") or dados.get("subtype") != "success":
        raise _erro_da_saida(texto or (proc.stderr or "").strip(), dados.get("api_error_status"))

    uso_tokens = dados.get("usage") or {}
    return RespostaIA(
        texto=texto,
        tokens_entrada=sum(
            int(uso_tokens.get(campo) or 0)
            for campo in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        ),
        tokens_saida=int(uso_tokens.get("output_tokens") or 0),
        modelo=modelo,
    )


def _erro_da_saida(detalhe: str, status=None) -> ErroProvedorIA:
    texto = (detalhe or "").lower()
    resumo = (detalhe or "sem detalhe").strip()[:300]
    if status == 429 or any(sinal in texto for sinal in _SINAIS_DE_LIMITE):
        return LimiteDoPlanoAtingido(f"Limite de uso do plano Claude atingido ({resumo}).")
    if any(sinal in texto for sinal in ("/login", "not logged in", "invalid api key", "authentication")):
        return ErroProvedorIA("O Claude Code não está logado no plano. Rode `claude` no terminal e faça login.")
    return ErroProvedorIA(f"O Claude Code devolveu erro: {resumo}")


def testar_claude() -> RespostaIA:
    """Pergunta mínima com a configuração salva do chat (botão 🔌 do painel)."""
    return chamar_claude(
        "Responda em português do Brasil, em uma frase curta.",
        "Confirme que a conexão com o Cérebro da loja está funcionando.",
        uso="chat", timeout=120,
    )
