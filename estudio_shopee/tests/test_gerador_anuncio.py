"""
tests/test_gerador_anuncio.py
==============================
Testes OFFLINE de `estudio_shopee/gerador_anuncio.py` (T-001 + T-002).

Nenhum teste faz chamada de rede real, nem depende de `OPENAI_API_KEY` real
estar setada no ambiente: toda chamada HTTP (`HTTP_SESSION.post`) é mockada
via `monkeypatch` do pytest, e `OPENAI_API_KEY` é sempre sobrescrita
explicitamente em cada teste (para "sk-fake-para-teste" ou para vazia,
conforme o caso), nunca deixada no valor real que porventura exista no
ambiente local.

Cobre os 5 casos mínimos exigidos por T-005:
1. `OPENAI_API_KEY` ausente -> `ErroGeracaoAnuncio`, sem tentar rede.
2. Resposta HTTP com status de erro -> `ErroGeracaoAnuncio`.
3. `content` da resposta não é JSON válido -> `ErroGeracaoAnuncio`.
4. JSON válido mas faltando uma chave esperada -> `ErroGeracaoAnuncio`.
5. Caminho feliz: resposta mockada com JSON completo -> `gerar_anuncio_shopee`
   retorna o dict esperado com as 3 chaves.

Rodar:  python -m pytest Local_AI/estudio_shopee/tests/test_gerador_anuncio.py -v
"""

import json
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gerador_anuncio  # noqa: E402
from gerador_anuncio import ErroGeracaoAnuncio, gerar_anuncio_shopee  # noqa: E402


IMAGEM_BYTES_FAKE = b"conteudo-fake-de-imagem-para-teste"
CONTEXTO_PRODUTO_FAKE = {
    "produto": "Suporte de Celular Articulado",
    "cor": "Preto",
    "estilo": "Fundo branco de catálogo",
}


class _RespostaFake:
    """Stub mínimo do objeto `Response` de `requests` — só com o que
    `chamar_openai_visao` de fato usa (`raise_for_status`, `json`, `text`,
    `status_code`). Evita depender de `requests` real na rede."""

    def __init__(self, status_code=200, json_data=None, texto=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = texto

    def raise_for_status(self):
        if self.status_code >= 400:
            erro = requests.exceptions.HTTPError(f"{self.status_code} erro simulado")
            erro.response = self
            raise erro

    def json(self):
        if self._json_data is None:
            raise ValueError("resposta fake sem corpo JSON")
        return self._json_data


def _resposta_openai_com_content(content, status_code=200):
    """Monta uma resposta fake no formato de envelope da API OpenAI Chat
    Completions, com `content` sendo a string bruta que o "modelo" devolveu
    (ainda não decodificada como o JSON do anúncio em si)."""
    return _RespostaFake(
        status_code=status_code,
        json_data={"choices": [{"message": {"content": content}}]},
    )


def _mock_post_nunca_deve_ser_chamado(monkeypatch):
    """Instala em `HTTP_SESSION.post` um mock que derruba o teste se for
    chamado — usado no caso em que a chamada de rede nem deveria ser
    tentada (falha cedo por credencial ausente)."""

    def _post(*args, **kwargs):
        raise AssertionError("HTTP_SESSION.post não deveria ter sido chamado")

    monkeypatch.setattr(gerador_anuncio.HTTP_SESSION, "post", _post)


def test_chave_ausente_nao_tenta_rede(monkeypatch):
    """Caso 1: OPENAI_API_KEY ausente -> ErroGeracaoAnuncio, sem chamada HTTP."""
    monkeypatch.setattr(gerador_anuncio, "OPENAI_API_KEY", "")
    _mock_post_nunca_deve_ser_chamado(monkeypatch)

    with pytest.raises(ErroGeracaoAnuncio, match="OPENAI_API_KEY"):
        gerar_anuncio_shopee(IMAGEM_BYTES_FAKE, CONTEXTO_PRODUTO_FAKE)


def test_resposta_http_de_erro(monkeypatch):
    """Caso 2: API responde com status de erro (ex.: 500) -> ErroGeracaoAnuncio."""
    monkeypatch.setattr(gerador_anuncio, "OPENAI_API_KEY", "sk-fake-para-teste")
    resposta = _RespostaFake(status_code=500, texto="internal error simulado")
    monkeypatch.setattr(gerador_anuncio.HTTP_SESSION, "post", lambda *a, **k: resposta)

    with pytest.raises(ErroGeracaoAnuncio, match="500"):
        gerar_anuncio_shopee(IMAGEM_BYTES_FAKE, CONTEXTO_PRODUTO_FAKE)


def test_content_nao_e_json_valido(monkeypatch):
    """Caso 3: content da resposta não é um JSON válido -> ErroGeracaoAnuncio."""
    monkeypatch.setattr(gerador_anuncio, "OPENAI_API_KEY", "sk-fake-para-teste")
    resposta = _resposta_openai_com_content("isso não é um JSON{{{")
    monkeypatch.setattr(gerador_anuncio.HTTP_SESSION, "post", lambda *a, **k: resposta)

    with pytest.raises(ErroGeracaoAnuncio, match="JSON"):
        gerar_anuncio_shopee(IMAGEM_BYTES_FAKE, CONTEXTO_PRODUTO_FAKE)


def test_json_valido_faltando_chave_esperada(monkeypatch):
    """Caso 4: JSON válido mas faltando 'palavras_chave' -> ErroGeracaoAnuncio."""
    monkeypatch.setattr(gerador_anuncio, "OPENAI_API_KEY", "sk-fake-para-teste")
    content = json.dumps({
        "titulo": "Suporte de Celular Articulado Preto para Mesa",
        "descricao": "Descrição completa do produto, sem palavras-chave.",
    })
    resposta = _resposta_openai_com_content(content)
    monkeypatch.setattr(gerador_anuncio.HTTP_SESSION, "post", lambda *a, **k: resposta)

    with pytest.raises(ErroGeracaoAnuncio, match="palavras_chave"):
        gerar_anuncio_shopee(IMAGEM_BYTES_FAKE, CONTEXTO_PRODUTO_FAKE)


def test_caminho_feliz_retorna_anuncio_completo(monkeypatch):
    """Caso 5: resposta mockada com JSON completo e válido -> devolve o dict
    esperado com as 3 chaves, e a mensagem enviada de fato inclui a imagem."""
    monkeypatch.setattr(gerador_anuncio, "OPENAI_API_KEY", "sk-fake-para-teste")
    esperado = {
        "titulo": "Suporte de Celular Articulado Preto para Mesa de Estudo",
        "descricao": "Organize seu espaço com este suporte articulado em PLA preto...",
        "palavras_chave": ["suporte celular", "suporte de mesa", "organizador de mesa"],
    }
    resposta = _resposta_openai_com_content(json.dumps(esperado))
    chamadas = []

    def _post(url, **kwargs):
        chamadas.append({"url": url, **kwargs})
        return resposta

    monkeypatch.setattr(gerador_anuncio.HTTP_SESSION, "post", _post)

    resultado = gerar_anuncio_shopee(
        IMAGEM_BYTES_FAKE, CONTEXTO_PRODUTO_FAKE, historico_estilo="Tom informal e direto."
    )

    assert resultado == esperado
    # A chamada HTTP foi feita exatamente uma vez, com a imagem embutida na
    # mensagem multimodal enviada (não é só um "mock que sempre passa").
    assert len(chamadas) == 1
    payload = chamadas[0]["json"]
    assert payload["messages"][0]["role"] == "system"
    conteudo_usuario = payload["messages"][1]["content"]
    assert any(bloco.get("type") == "image_url" for bloco in conteudo_usuario)
    assert any(bloco.get("type") == "text" for bloco in conteudo_usuario)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
