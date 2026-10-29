"""
Testes OFFLINE do motor de IA pelo plano Claude (cerebro/provedor_ia.py) e da
parada da auditoria no limite do plano (cerebro/motor_ia.processar_em_lotes).

Nenhum teste chama o Claude de verdade: subprocess.run, shutil.which e
provedor_ia.chamar_claude são substituídos por dublês.

Rodar:  python tests/test_provedor_ia.py  (pytest também funciona)
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cerebro import motor_ia, provedor_ia  # noqa: E402
from cerebro.dossie import _montar_dados_variacao  # noqa: E402
from tests.test_cerebro_correlacoes import _linha_base  # noqa: E402


class _Processo:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def _saida_cli(texto, erro=False, status=None):
    return json.dumps({
        "type": "result", "subtype": "error" if erro else "success", "is_error": erro,
        "api_error_status": status, "result": texto,
        "usage": {"input_tokens": 5, "cache_creation_input_tokens": 1000,
                  "cache_read_input_tokens": 200, "output_tokens": 40},
    })


class _Duble:
    """Substitui shutil.which e subprocess.run durante um teste."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    def __enter__(self):
        self._which, self._run = provedor_ia.shutil.which, provedor_ia.subprocess.run
        provedor_ia.shutil.which = lambda nome: r"C:\fake\claude.CMD"

        def run(comando, **kwargs):
            self.chamadas.append((comando, kwargs))
            resposta = self.respostas.pop(0)
            return resposta(comando, kwargs) if callable(resposta) else resposta

        provedor_ia.subprocess.run = run
        return self

    def __exit__(self, *exc):
        provedor_ia.shutil.which, provedor_ia.subprocess.run = self._which, self._run


class _Ambiente:
    """Define variáveis de ambiente só durante o teste."""

    def __init__(self, **valores):
        self.valores = valores

    def __enter__(self):
        self.antes = {k: os.environ.get(k) for k in self.valores}
        os.environ.update(self.valores)

    def __exit__(self, *exc):
        for chave, valor in self.antes.items():
            if valor is None:
                os.environ.pop(chave, None)
            else:
                os.environ[chave] = valor


def test_chamada_usa_o_plano_sem_chave_de_api_e_prompt_longo_por_arquivo():
    sistema_lido = []

    def responder(comando, kwargs):
        caminho = comando[comando.index("--system-prompt-file") + 1]
        sistema_lido.append(Path(caminho).read_text(encoding="utf-8"))
        return _Processo(_saida_cli('{"resultados": []}'))

    sistema = "REGRAS DO CONSELHO " * 2000  # bem acima do limite de 8.191 caracteres do claude.cmd
    with _Ambiente(ANTHROPIC_API_KEY="sk-ant-nao-pode-vazar", CLAUDE_MODEL_30D="opus", CLAUDE_EFFORT_30D="high"):
        with _Duble([responder]) as duble:
            resposta = provedor_ia.chamar_claude(sistema, "Auditoria:{}", uso="30d")

    comando, kwargs = duble.chamadas[0]
    assert comando[1] == "-p"
    assert comando[comando.index("--model") + 1] == "opus"
    assert comando[comando.index("--effort") + 1] == "high"
    assert comando[comando.index("--tools") + 1] == ""
    assert "--safe-mode" in comando and "--no-session-persistence" in comando
    assert sistema_lido == [sistema]
    assert kwargs["input"] == "Auditoria:{}"
    assert "ANTHROPIC_API_KEY" not in kwargs["env"]  # nunca cai em cobrança por uso
    assert resposta.tokens_entrada == 1205 and resposta.tokens_saida == 40


def test_limite_do_plano_vira_excecao_propria():
    with _Duble([_Processo(_saida_cli("Claude AI usage limit reached|1757880000", erro=True), returncode=1)]):
        try:
            provedor_ia.chamar_claude("s", "m", uso="7d")
        except provedor_ia.LimiteDoPlanoAtingido:
            return
    raise AssertionError("deveria ter levantado LimiteDoPlanoAtingido")


def test_sem_login_explica_como_resolver():
    with _Duble([_Processo(_saida_cli("Invalid API key · Please run /login", erro=True), returncode=1)]):
        try:
            provedor_ia.chamar_claude("s", "m", uso="chat")
        except provedor_ia.LimiteDoPlanoAtingido:
            raise AssertionError("falta de login não é limite do plano")
        except provedor_ia.ErroProvedorIA as exc:
            assert "login" in str(exc)
            return
    raise AssertionError("deveria ter levantado ErroProvedorIA")


def test_status_recusa_login_que_cobraria_por_uso():
    por_chave = json.dumps({"loggedIn": True, "authMethod": "apiKey", "subscriptionType": None})
    with _Duble([_Processo(por_chave)]):
        status = provedor_ia.status_claude_code(forcar=True)
    assert not status["ok"] and "cobraria" in status["mensagem"]

    pelo_plano = json.dumps({"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "pro", "email": "x@y.com"})
    with _Duble([_Processo(pelo_plano)]):
        status = provedor_ia.status_claude_code(forcar=True)
    assert status["ok"] and status["plano"] == "pro"
    provedor_ia.limpar_status()


def test_configuracao_invalida_cai_nos_padroes():
    with _Ambiente(IA_PROVEDOR="qualquer", CLAUDE_MODEL_7D="gpt-4", CLAUDE_EFFORT_7D="ultra", CLAUDE_MAX_CHAMADAS_AUDITORIA="abc"):
        assert provedor_ia.provedor() == "openai"
        assert provedor_ia.modelo_claude("7d") == "sonnet"
        assert provedor_ia.esforco_claude("7d") == "medium"
        assert provedor_ia.max_chamadas_auditoria() == 25
    with _Ambiente(CLAUDE_MODEL_CHAT="claude-opus-5"):
        assert provedor_ia.modelo_claude("chat") == "claude-opus-5"  # nome completo também vale


# ── Auditoria parando no limite do plano ─────────────────────────────────────

def _dossie(quantidade: int) -> list[dict]:
    dossie = []
    for i in range(quantidade):
        variacao = _montar_dados_variacao(_linha_base(
            item_id=1000 + i, model_id=2000 + i, qtd_variacoes_produto=1, vendas_30d_item_total=15,
        ))
        variacao["MEMORIA_ESTRATEGICA_30D"] = None
        dossie.append(variacao)
    return dossie


def _claude_falso(chamadas: list, falhar_na: int | None = None):
    def responder(sistema, mensagem, *, uso, timeout=600):
        chamadas.append(uso)
        if falhar_na is not None and len(chamadas) == falhar_na:
            raise provedor_ia.LimiteDoPlanoAtingido("Limite de uso do plano Claude atingido (teste).")
        lote = json.loads(mensagem.removeprefix("Auditoria:"))
        resultados = [
            {"item_id": p["item_id"], "model_id": v["model_id"], "tipo_acao": "MANTER",
             "novo_preco_sugerido": v["preco_atual"], "recomendacao_executiva": "ok"}
            for p in lote for v in p["variacoes_ativas"]
        ]
        return provedor_ia.RespostaIA(json.dumps({"resultados": resultados}), 1000, 500, "sonnet")
    return responder


def _auditar(quantidade: int, responder, **ambiente) -> tuple[list[dict], dict]:
    original = provedor_ia.chamar_claude
    provedor_ia.chamar_claude = responder
    try:
        with _Ambiente(IA_PROVEDOR="claude_code", **ambiente):
            telemetria = {}
            resultados = motor_ia.processar_em_lotes(
                _dossie(quantidade), "30d", modo_economico=False, telemetria=telemetria,
            )
    finally:
        provedor_ia.chamar_claude = original
    return resultados, telemetria


def test_auditoria_para_no_limite_do_plano_e_adia_o_resto():
    # 9 SKUs no 30d pelo plano = lotes de 4, 4 e 1. O 2º lote bate no limite.
    chamadas = []
    resultados, telemetria = _auditar(9, _claude_falso(chamadas, falhar_na=2))

    assert len(chamadas) == 2  # parou na hora: o 3º lote nem foi tentado
    analisados = [r for r in resultados if not r.get("falha_modelo_externo")]
    adiados = [r for r in resultados if r.get("falha_modelo_externo")]
    assert len(analisados) == 4 and len(adiados) == 5  # adiados voltam na próxima execução
    assert telemetria["lotes_adiados"] == 2
    assert "Limite" in telemetria["motivo_adiamento"]
    assert telemetria["chamadas"] == 1


def test_teto_de_chamadas_por_auditoria_adia_o_resto():
    chamadas = []
    resultados, telemetria = _auditar(9, _claude_falso(chamadas), CLAUDE_MAX_CHAMADAS_AUDITORIA="1")

    assert len(chamadas) == 1
    assert telemetria["lotes_adiados"] == 2
    assert "Teto de 1" in telemetria["motivo_adiamento"]
    assert sum(1 for r in resultados if r.get("falha_modelo_externo")) == 5


if __name__ == "__main__":
    testes = [(nome, f) for nome, f in globals().items() if nome.startswith("test_") and callable(f)]
    for nome, funcao in testes:
        funcao()
        print(f"  ok  {nome}")
    print(f"{len(testes)} teste(s) passaram.")
