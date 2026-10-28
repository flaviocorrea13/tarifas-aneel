"""Testes dos cálculos puros de :mod:`custom_components.tarifas_aneel.calc`.

Valores de referência usados nas amostras reais da Fase 0:
Eletropaulo B1 Convencional Residencial — TUSD 472,42 e TE 316,96 R$/MWh
(0,47242 e 0,31696 R$/kWh), ICMS 18% -> 962,66 R$/MWh (0,96265853...).

Não importa o Home Assistant: :mod:`calc` é puro (const + models).
"""

from __future__ import annotations

import pytest

from custom_components.tarifas_aneel.calc import (
    aplicar_impostos,
    calcular_tarifa,
    rsmwh_para_rskwh,
    validar_aliquotas,
)

TUSD = 0.47242
TE = 0.31696
ADICIONAL_AMARELA = 0.005  # 5,00 R$/MWh da bandeira Amarela
ICMS_18 = 0.18


def test_rsmwh_para_rskwh() -> None:
    """Divide por 1000 (R$/MWh -> R$/kWh)."""
    assert rsmwh_para_rskwh(472.42) == pytest.approx(0.47242)
    assert rsmwh_para_rskwh(0) == 0


def test_calcular_tarifa_sem_aliquotas() -> None:
    """Sem impostos (padrão), a final é a própria soma TUSD+TE."""
    resultado = calcular_tarifa(TUSD, TE, 0)
    assert resultado.tarifa_sem_impostos == pytest.approx(TUSD + TE)
    assert resultado.tarifa_com_bandeira == pytest.approx(TUSD + TE)
    assert resultado.tarifa_com_impostos == pytest.approx(TUSD + TE)
    assert resultado.tarifa_final == pytest.approx(TUSD + TE)
    # Contrato dos campos expostos pela plataforma sensor:
    assert resultado.tarifa_tusd == pytest.approx(TUSD)
    assert resultado.tarifa_te == pytest.approx(TE)
    assert resultado.adicional_bandeira == 0


def test_gross_up_por_dentro_icms_18() -> None:
    """Gross-up \"por dentro\": preco / (1 - 0.18) — amostra real."""
    resultado = calcular_tarifa(TUSD, TE, 0, ICMS_18, 0, 0)
    esperado = (TUSD + TE) / 0.82
    assert resultado.tarifa_final == pytest.approx(esperado)
    assert esperado == pytest.approx(0.9626585366, abs=1e-9)
    # Servindo o painel: com_impostos < final quando há bandeira adicional.
    assert resultado.tarifa_com_impostos == pytest.approx(esperado)


def test_gross_up_com_bandeira_acionada() -> None:
    """Final embute imposto e bandeira: (TUSD+TE+adicional)/(1-soma)."""
    resultado = calcular_tarifa(TUSD, TE, ADICIONAL_AMARELA, ICMS_18, 0, 0)
    esperado = (TUSD + TE + ADICIONAL_AMARELA) / 0.82
    assert resultado.tarifa_com_bandeira == pytest.approx(TUSD + TE + ADICIONAL_AMARELA)
    assert resultado.tarifa_final == pytest.approx(esperado)
    assert resultado.tarifa_final > resultado.tarifa_com_impostos


def test_validar_aliquotas_soma_maior_igual_um() -> None:
    """Soma >= 100% impossibilita o gross-up (divisão por zero/negativo)."""
    with pytest.raises(ValueError, match="soma"):
        validar_aliquotas(0.5, 0.3, 0.3)
    with pytest.raises(ValueError):
        validar_aliquotas(1.0, 0, 0)


def test_validar_aliquotas_negativas() -> None:
    """Alíquota negativa é erro."""
    with pytest.raises(ValueError, match="negativas"):
        validar_aliquotas(-0.01, 0, 0)


def test_aplicar_impostos_preco_negativo() -> None:
    """Preço sem impostos negativo é erro."""
    with pytest.raises(ValueError, match="negativo"):
        aplicar_impostos(-1.0, 0, 0, 0)


@pytest.mark.parametrize(
    ("tusd", "te", "adicional"),
    [
        (-0.1, 0.3, 0),
        (0.4, -0.02, 0),
        (0.4, 0.3, -0.001),
    ],
)
def test_calcular_tarifa_valores_negativos(
    tusd: float, te: float, adicional: float
) -> None:
    """TUSD/TE/adicional negativos levantam ``ValueError``."""
    with pytest.raises(ValueError):
        calcular_tarifa(tusd, te, adicional, ICMS_18, 0, 0)


def test_calcular_tarifa_aliquota_invalida_levanta() -> None:
    """Gross-up impossível direto em :func:`calcular_tarifa` também levanta."""
    with pytest.raises(ValueError):
        calcular_tarifa(TUSD, TE, 0, 0.66, 0.2, 0.2)


def test_impostos_redondos() -> None:
    """Cenário fácil de conferir mentalmente: 100 / (1 - 50%) = 200."""
    assert calcular_tarifa(0.5, 0.5, 0, 0.5, 0, 0).tarifa_final == pytest.approx(
        2.0
    )
