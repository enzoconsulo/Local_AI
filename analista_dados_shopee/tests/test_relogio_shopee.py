"""
Testes OFFLINE da compensação do relógio em utils/shopee_core.chamar_shopee_api.

Cenário real (29/10/2026): serviço de horário do Windows desativado, PC 12 min
atrasado, e a Shopee recusando tudo com "Timestamp is expired". O app deve medir
o desvio pelo cabeçalho Date da resposta, repetir com o horário corrigido e
deixar a causa legível para a UI.

Rodar:  python -m pytest tests/test_relogio_shopee.py
"""

import sys
import time
from email.utils import formatdate
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import shopee_core, tunel_shopee  # noqa: E402

ATRASO_S = 740  # PC 12 min 20 s atrasado, como no caso real


class RespostaFalsa:
    def __init__(self, corpo, data_servidor=None):
        self.status_code = 200
        self.headers = {"Date": formatdate(data_servidor, usegmt=True)} if data_servidor else {}
        self._corpo = corpo

    def json(self):
        return self._corpo

    def raise_for_status(self):
        pass


def _recusa_timestamp():
    return RespostaFalsa(
        {"error": "error_param", "message": "Timestamp is expired."},
        data_servidor=time.time() + ATRASO_S,
    )


@pytest.fixture
def shopee(monkeypatch):
    """chamar_shopee_api sem rede: token e túnel fingidos, respostas em fila."""
    monkeypatch.setattr(shopee_core, "_DESVIO_RELOGIO_S", 0.0)
    monkeypatch.setattr(shopee_core, "_ULTIMO_ERRO", None)
    monkeypatch.setattr(shopee_core, "obter_access_token", lambda: "token")
    monkeypatch.setattr(tunel_shopee, "garantir_tunel", lambda: True)
    chamadas = []
    fila = []

    def get(url, params=None, timeout=None):
        chamadas.append(params)
        return fila.pop(0)

    monkeypatch.setattr(shopee_core._HTTP_SESSION, "get", get)
    return fila, chamadas


def test_timestamp_recusado_compensa_o_relogio_e_repete(shopee):
    fila, chamadas = shopee
    fila += [_recusa_timestamp(), RespostaFalsa({"response": {"item": [1, 2]}})]

    resultado = shopee_core.chamar_shopee_api("/api/v2/product/get_item_list")

    assert resultado == {"item": [1, 2]}
    assert len(chamadas) == 2
    # A segunda assinatura já sai no horário da Shopee (margem para o teste rodar).
    assert abs(chamadas[1]["timestamp"] - (time.time() + ATRASO_S)) < 5
    aviso = shopee_core.aviso_relogio()
    assert aviso and "12 min atrasado" in aviso


def test_recusa_persistente_nao_entra_em_loop_e_explica_a_causa(shopee):
    fila, chamadas = shopee
    fila += [_recusa_timestamp(), _recusa_timestamp(), _recusa_timestamp()]

    assert shopee_core.chamar_shopee_api("/api/v2/product/get_item_list") is None
    # 1ª recusa corrige o relógio; a 2ª, com o mesmo desvio, desiste em vez de repetir.
    assert len(chamadas) == 2
    erro = shopee_core.ultimo_erro_shopee()
    assert "horário" in erro and "atrasado" in erro


def test_relogio_em_dia_nao_gera_aviso(shopee):
    fila, _ = shopee
    fila.append(RespostaFalsa({"response": {}}, data_servidor=time.time()))

    assert shopee_core.chamar_shopee_api("/api/v2/product/get_item_list") == {}
    assert shopee_core.aviso_relogio() is None


def test_outro_erro_da_api_fica_registrado_para_a_ui(shopee):
    fila, _ = shopee
    fila.append(RespostaFalsa({"error": "error_auth", "message": "Invalid partner"}))

    assert shopee_core.chamar_shopee_api("/api/v2/product/get_item_list") is None
    assert shopee_core.ultimo_erro_shopee() == (
        "Shopee API Erro (/api/v2/product/get_item_list): error_auth - Invalid partner"
    )


@pytest.mark.parametrize("cabecalhos", [{}, {"Date": ""}, {"Date": "ontem à tarde"}])
def test_cabecalho_date_ausente_ou_ilegivel(cabecalhos):
    assert tunel_shopee.desvio_pelo_cabecalho(cabecalhos) is None
