"""Testes dos cálculos puros de :mod:`custom_components.tarifas_aneel.calc`.

Valores de referência usados nas amostras reais da Fase 0:
Eletropaulo B1 Convencional Residencial — TUSD 472,42 e TE 316,96 R$/MWh
(0,47242 e 0,31696 R$/kWh). Os testes da fórmula nova usam a amostra
pedida na revisão: TUSD 0,66201 + TE 0,32459 = 0,98660 R$/kWh.

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

# Amostra da revisão: TUSD + TE = 0,98660 e bandeira de 0,01885.
TUSD_AMOSTRA = 0.66201
TE_AMOSTRA = 0.32459
BANDEIRA_AMOSTRA = 0.01885
ICMS_AMOSTRA = 0.17
PIS_AMOSTRA = 0.0165
COFINS_AMOSTRA = 0.076
DIVISOR_AMOSTRA = (1 - ICMS_AMOSTRA) * (1 - PIS_AMOSTRA - COFINS_AMOSTRA)


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


def test_tres_aliquotas_zero_igual_tarifa_sem_impostos() -> None:
    """ICMS = PIS = COFINS = 0 devolve exatamente a tarifa sem impostos."""
    resultado = calcular_tarifa(TUSD, TE, BANDEIRA_AMOSTRA, 0, 0, 0)
    assert resultado.tarifa_com_impostos == pytest.approx(TUSD + TE)
    assert resultado.tarifa_final == pytest.approx(
        TUSD + TE + BANDEIRA_AMOSTRA
    )


def test_formula_pis_cofins_sem_icms_na_base() -> None:
    """tarifa / ((1 - ICMS) * (1 - PIS - COFINS)) — amostra da revisão."""
    resultado = calcular_tarifa(
        TUSD_AMOSTRA,
        TE_AMOSTRA,
        0,
        ICMS_AMOSTRA,
        PIS_AMOSTRA,
        COFINS_AMOSTRA,
    )
    assert resultado.tarifa_sem_impostos == pytest.approx(0.98660)
    assert resultado.tarifa_com_impostos == pytest.approx(1.3098, abs=1e-4)
    assert resultado.tarifa_final == pytest.approx(1.3098, abs=1e-4)
    # Explicitando a fórmula, para documentar o divisor usado.
    assert resultado.tarifa_final == pytest.approx(
        0.98660 / DIVISOR_AMOSTRA
    )


def test_formula_pis_cofins_sem_icms_com_bandeira() -> None:
    """A bandeira entra na base antes do gross-up."""
    resultado = calcular_tarifa(
        TUSD_AMOSTRA,
        TE_AMOSTRA,
        BANDEIRA_AMOSTRA,
        ICMS_AMOSTRA,
        PIS_AMOSTRA,
        COFINS_AMOSTRA,
    )
    assert resultado.tarifa_com_bandeira == pytest.approx(
        0.98660 + BANDEIRA_AMOSTRA
    )
    assert resultado.tarifa_final == pytest.approx(1.3349, abs=1e-3)
    assert resultado.tarifa_final == pytest.approx(
        (0.98660 + BANDEIRA_AMOSTRA) / DIVISOR_AMOSTRA
    )


def test_formula_antiga_quando_opcao_desligada() -> None:
    """Com a opção desligada, todos os tributos usam a mesma base."""
    resultado = calcular_tarifa(
        TUSD_AMOSTRA,
        TE_AMOSTRA,
        0,
        ICMS_AMOSTRA,
        PIS_AMOSTRA,
        COFINS_AMOSTRA,
        pis_cofins_sem_icms=False,
    )
    esperado = 0.98660 / (
        1 - (ICMS_AMOSTRA + PIS_AMOSTRA + COFINS_AMOSTRA)
    )
    assert resultado.tarifa_final == pytest.approx(esperado)
    # A fórmula antiga divide por um divisor menor (ICMS e PIS/COFINS na
    # mesma base) e, por isso, gera preço maior que a nova.
    nova = calcular_tarifa(
        TUSD_AMOSTRA,
        TE_AMOSTRA,
        0,
        ICMS_AMOSTRA,
        PIS_AMOSTRA,
        COFINS_AMOSTRA,
    )
    assert nova.tarifa_final < resultado.tarifa_final


def test_gross_up_por_dentro_icms_18() -> None:
    """Só ICMS: as duas fórmulas coincidem em preco / (1 - 0.18)."""
    resultado = calcular_tarifa(TUSD, TE, 0, ICMS_18, 0, 0)
    esperado = (TUSD + TE) / 0.82
    assert resultado.tarifa_final == pytest.approx(esperado)
    assert esperado == pytest.approx(0.9626585366, abs=1e-9)
    # Servindo o painel: com_impostos == final quando não há bandeira.
    assert resultado.tarifa_com_impostos == pytest.approx(esperado)


def test_gross_up_com_bandeira_acionada() -> None:
    """Final embute imposto e bandeira: (TUSD+TE+adicional)/(1-ICMS)."""
    resultado = calcular_tarifa(TUSD, TE, ADICIONAL_AMARELA, ICMS_18, 0, 0)
    esperado = (TUSD + TE + ADICIONAL_AMARELA) / 0.82
    assert resultado.tarifa_com_bandeira == pytest.approx(
        TUSD + TE + ADICIONAL_AMARELA
    )
    assert resultado.tarifa_final == pytest.approx(esperado)
    assert resultado.tarifa_final > resultado.tarifa_com_impostos


def test_validar_aliquotas_icms_maior_igual_um() -> None:
    """ICMS >= 100% impossibilita o gross-up."""
    with pytest.raises(ValueError, match="ICMS"):
        validar_aliquotas(1.0, 0, 0)
    with pytest.raises(ValueError, match="ICMS"):
        validar_aliquotas(1.2, 0.01, 0.01)


def test_validar_aliquotas_pis_cofins_soma_maior_igual_um() -> None:
    """PIS + COFINS >= 100% impossibilita a base sem ICMS."""
    with pytest.raises(ValueError, match=r"PIS \+ COFINS"):
        validar_aliquotas(0.17, 0.5, 0.5)
    with pytest.raises(ValueError, match=r"PIS \+ COFINS"):
        validar_aliquotas(0.0, 0.6, 0.4)


def test_validar_aliquotas_formula_antiga_soma_maior_igual_um() -> None:
    """Na fórmula antiga a soma total também precisa ser < 100%."""
    with pytest.raises(ValueError, match="soma"):
        validar_aliquotas(
            0.9, 0.06, 0.06, pis_cofins_sem_icms=False
        )
    # Mesmas alíquotas são válidas na fórmula nova (ICMS e PIS/COFINS
    # ficam em bases separadas).
    assert validar_aliquotas(0.9, 0.06, 0.06) == pytest.approx(
        (1 - 0.9) * (1 - 0.12)
    )


def test_validar_aliquotas_negativas() -> None:
    """Alíquota negativa é erro."""
    with pytest.raises(ValueError, match="negativas"):
        validar_aliquotas(-0.01, 0, 0)


def test_aplicar_impostos_preco_negativo() -> None:
    """Preço sem impostos negativo é erro."""
    with pytest.raises(ValueError, match="negativo"):
        aplicar_impostos(-1.0, 0, 0, 0)


def test_aplicar_impostos_respeita_a_opcao_da_base() -> None:
    """A função pura aceita a escolha da base explicitamente."""
    preco = 0.98660
    nova = aplicar_impostos(preco, 0.17, 0.0165, 0.076)
    antiga = aplicar_impostos(
        preco, 0.17, 0.0165, 0.076, pis_cofins_sem_icms=False
    )
    assert nova == pytest.approx(preco / DIVISOR_AMOSTRA)
    assert antiga == pytest.approx(preco / (1 - 0.2625))


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
        calcular_tarifa(TUSD, TE, 0, 1.0, 0, 0)
    with pytest.raises(ValueError):
        calcular_tarifa(TUSD, TE, 0, 0.17, 0.6, 0.4)


def test_impostos_redondos() -> None:
    """Cenário fácil de conferir mentalmente: 100 / (1 - 50%) = 200."""
    assert calcular_tarifa(0.5, 0.5, 0, 0.5, 0, 0).tarifa_final == pytest.approx(
        2.0
    )
