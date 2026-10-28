"""Testes da janela de posto tarifário (:func:`_posto_para_hora` do coordinator).

Janela padrão da integração: ponta 17:30-20:30 (horário de ponta típico
do Grupo B, configurável nas opções), com 1 h de intermediário
imediatamente antes e depois. Também cobre janela que cruza a meia-noite
e os casos de fronteira.
"""

from __future__ import annotations

from datetime import time

import pytest

pytest.importorskip("homeassistant")

from custom_components.tarifas_aneel.coordinator import _posto_para_hora


@pytest.mark.parametrize(
    ("hora", "esperado"),
    [
        (time(12, 0), "Fora ponta"),
        (time(16, 29), "Fora ponta"),
        (time(16, 30), "Intermediário"),  # 1 h antes da ponta
        (time(17, 29), "Intermediário"),
        (time(17, 30), "Ponta"),
        (time(20, 29), "Ponta"),
        (time(20, 30), "Intermediário"),  # 1 h depois da ponta
        (time(21, 29), "Intermediário"),
        (time(21, 30), "Fora ponta"),
    ],
)
def test_janela_padrao(hora: time, esperado: str) -> None:
    """Pontas padrão: ponta 17:30-20:30 (configurável nas opções)."""
    assert (
        _posto_para_hora(hora, time(17, 30), time(20, 30)) == esperado
    )


def test_meia_noite_fronteira() -> None:
    """00:00 ainda faz parte do depois (janela ponta cruza a meia-noite)."""
    assert _posto_para_hora(time(0, 0), time(22, 0), time(1, 0)) == "Ponta"


def test_janela_cruza_meia_noite() -> None:
    """Ponta 22:00-01:00: ponta nas duas margens, intermediário nas cercanias."""
    posto = _posto_para_hora
    assert posto(time(23, 30), time(22, 0), time(1, 0)) == "Ponta"
    assert posto(time(0, 30), time(22, 0), time(1, 0)) == "Ponta"
    assert posto(time(21, 30), time(22, 0), time(1, 0)) == "Intermediário"
    assert posto(time(1, 30), time(22, 0), time(1, 0)) == "Intermediário"
    assert posto(time(2, 30), time(22, 0), time(1, 0)) == "Fora ponta"


def test_ponta_de_uma_hora() -> None:
    """Ponta de apenas 1 h (18:00-19:00), conferência mental fácil."""
    posto = _posto_para_hora
    assert posto(time(17, 59), time(18, 0), time(19, 0)) == "Intermediário"
    assert posto(time(18, 0), time(18, 0), time(19, 0)) == "Ponta"
    assert posto(time(19, 0), time(18, 0), time(19, 0)) == "Intermediário"
