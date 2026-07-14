"""
cerebro/config.py
=================
Configuração central do Cérebro IA: credenciais OpenAI, modelos por horizonte,
sessão HTTP compartilhada, caminhos de cache e o vocabulário de ações.
"""

import functools
import os
import threading
import time
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from dotenv import load_dotenv


class MigracaoPendenteError(RuntimeError):
    """Uma migração de banco obrigatória não foi aplicada.

    O núcleo do cérebro levanta esta exceção em vez de chamar st.error/st.stop:
    quem decide como exibir o problema é a camada de interface (página 3 hoje,
    página 4 amanhã), não a camada de dados.
    """


def memoizar_ttl(ttl_segundos: int, reavaliar_falsos: bool = True):
    """Cache leve em memória por processo — substitui o st.cache_data no núcleo,
    que precisa funcionar fora de um contexto Streamlit.

    Com reavaliar_falsos=True, resultados falsy não ficam presos no cache:
    ideal para sondagens de migração — assim que o usuário aplica a migração,
    o app a enxerga na próxima chamada, sem esperar o TTL expirar.
    """
    def decorador(fn):
        cache: dict = {}
        trava = threading.Lock()

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            chave = (args, tuple(sorted(kwargs.items())))
            agora = time.monotonic()
            with trava:
                hit = cache.get(chave)
                if hit and agora - hit[0] < ttl_segundos and (hit[1] or not reavaliar_falsos):
                    return hit[1]
            valor = fn(*args, **kwargs)
            with trava:
                cache[chave] = (agora, valor)
            return valor

        wrapper.limpar_cache = cache.clear
        return wrapper
    return decorador

ROOT_DIR = Path(__file__).resolve().parent.parent

# override=True força o Python a usar a porta 5433 e ignora variáveis falsas do Windows
load_dotenv(ROOT_DIR / "CHAVES_DADOS.env", override=True)

# ── OpenAI (inferência externa direta: sem RunPod, LiteLLM local ou GPU) ──────
OPENAI_API_BASE_URL = (os.getenv("OPENAI_API_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
OPENAI_CHAT_COMPLETIONS_URL = (
    OPENAI_API_BASE_URL
    if OPENAI_API_BASE_URL.endswith("/chat/completions")
    else f"{OPENAI_API_BASE_URL}/chat/completions"
)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL_7D = os.getenv("OPENAI_MODEL_7D", "gpt-5.4").strip()
OPENAI_MODEL_30D = os.getenv("OPENAI_MODEL_30D", "gpt-5.5").strip()
OPENAI_REASONING_7D = os.getenv("OPENAI_REASONING_7D", "low").strip().lower()
OPENAI_REASONING_30D = os.getenv("OPENAI_REASONING_30D", "medium").strip().lower()

# Chat da página 4 (text-to-SQL): tarefas curtas e frequentes — por padrão usa
# o mesmo modelo barato do horizonte 7d com raciocínio mínimo.
OPENAI_MODEL_CHAT = (os.getenv("OPENAI_MODEL_CHAT") or "").strip() or OPENAI_MODEL_7D
OPENAI_REASONING_CHAT = os.getenv("OPENAI_REASONING_CHAT", "low").strip().lower()

# Versão do contrato dado→prompt→saída. Faz parte do fingerprint do cache
# semântico: mudanças de tratamento de dados ou de prompt invalidam o cache
# de forma controlada em vez de reutilizarem análises incompatíveis.
# v3: regra 10 (ACOS de campanha vs. retorno líquido total) após o teste E2E
# de 14/07/2026 flagrar leitura invertida do sinal de ads no parecer CMO.
VERSAO_PROMPT = "openai-json-v3"

HTTP_SESSION = requests.Session()
HTTP_SESSION.mount("http://", HTTPAdapter(pool_connections=2, pool_maxsize=4, max_retries=0))
HTTP_SESSION.mount("https://", HTTPAdapter(pool_connections=2, pool_maxsize=4, max_retries=0))

# ── Cache das auditorias em disco (sobrevive a F5 e reinício do app) ─────────
CACHE_AUDITORIA = ROOT_DIR / "ultima_auditoria.json"
CACHE_AUDITORIA_7D = ROOT_DIR / "ultima_auditoria_7d.json"
CACHE_AUDITORIA_30D = ROOT_DIR / "ultima_auditoria_30d.json"

# ── Vocabulário de ações ──────────────────────────────────────────────────────
ACTIONS_EXECUTAVEIS_SEGURAS = {"AUMENTAR_PRECO", "REDUZIR_PRECO", "CRIAR_PROMOCAO", "CRIAR_COMBO"}
ACTIONS_RECOMENDACAO_APENAS = {
    "PAUSAR_ADS",
    "AUMENTAR_BUDGET_ADS",
    "REDUZIR_BUDGET_ADS",
    "CRIAR_ADS",
    "EDITAR_ADS",
}
ACOES_VALIDAS = {
    "AUMENTAR_PRECO", "REDUZIR_PRECO", "CRIAR_PROMOCAO",
    "CRIAR_COMBO", "PAUSAR_ADS", "MANTER",
}


def modelo_para(horizonte: str) -> str:
    return OPENAI_MODEL_7D if horizonte == "7d" else OPENAI_MODEL_30D


def reasoning_para(horizonte: str) -> str:
    return OPENAI_REASONING_7D if horizonte == "7d" else OPENAI_REASONING_30D


def horizonte_em_dias(horizonte: str) -> int:
    if horizonte not in {"7d", "30d"}:
        raise ValueError("Horizonte de auditoria inválido. Use '7d' ou '30d'.")
    return 7 if horizonte == "7d" else 30


def classificar_modo_execucao(acao: str) -> tuple[str, str]:
    """Classifica se uma sugestão pode ser aplicada automaticamente ou apenas recomendada."""
    if acao in ACTIONS_EXECUTAVEIS_SEGURAS:
        return "EXECUTAR", "Ação operacional segura: o sistema pode aplicar após aprovação do usuário."
    if acao in ACTIONS_RECOMENDACAO_APENAS:
        return "RECOMENDAR", "Ação ligada a ads ou gasto: permanecerá como recomendação e revisão manual."
    return "RECOMENDAR", "Sem execução automática definida; siga o plano de ação recomendado."


def rotulo_acao(acao: str) -> str:
    return {
        "MANTER": "Monitorar",
        "PAUSAR_ADS": "Pausar ads",
        "AUMENTAR_PRECO": "Aumentar preço",
        "REDUZIR_PRECO": "Reduzir preço",
        "CRIAR_PROMOCAO": "Criar promoção",
        "CRIAR_COMBO": "Criar combo",
    }.get(acao, str(acao).replace("_", " ").title())


def explicar_acao(acao: str) -> tuple[str, str]:
    """Texto de interface: deixa explícito o efeito e o próximo passo de cada recomendação."""
    explicacoes = {
        "AUMENTAR_PRECO": ("O preço publicado da variação será elevado para o valor proposto.", "Aplique somente se a margem e a evidência estiverem adequadas."),
        "REDUZIR_PRECO": ("O preço publicado da variação será reduzido para o valor proposto.", "Confira o impacto na margem antes de confirmar."),
        "CRIAR_PROMOCAO": ("Será criada uma promoção temporária com o preço proposto.", "O preço de tabela não é alterado permanentemente."),
        "CRIAR_COMBO": ("Será criado um combo com desconto padrão de 10% para o produto.", "O preço exibido é uma referência; confira a oferta criada no Seller Center."),
        "PAUSAR_ADS": ("Nenhuma alteração é enviada por esta tela.", "Pause ou ajuste a campanha manualmente no Seller Center."),
    }
    return explicacoes.get(acao, ("A recomendação não altera nada até sua confirmação.", "Leia o parecer e valide a ação manualmente."))
