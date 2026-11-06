"""Caso numérico de referência rodando no harness do Home Assistant.

Complementa ``test_calc.py`` (função pura) exercitando o caminho real do
coordinator: opções em percentual, conversão para fração, aplicação do
gross-up e publicação em ``DadosAneel.calculos``.

Amostra da revisão: TUSD 0,66201 + TE 0,32459, ICMS 17%, PIS 1,65% e
COFINS 7,6%, com PIS/COFINS calculado sem ICMS na base. O preço final
esperado é 0,98660 / ((1 - 0,17) * (1 - 0,0165 - 0,076)) ≈ 1,3098.
"""

from __future__ import annotations

from datetime import date

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tarifas_aneel.api import TarifaFiltro
from custom_components.tarifas_aneel.const import (
    CONF_CLASSE,
    CONF_DETALHE,
    CONF_DISTRIBUIDORA,
    CONF_MODALIDADE,
    CONF_SUBCLASSE,
    CONF_SUBGRUPO,
    DOMAIN,
    OPT_COFINS,
    OPT_ICMS,
    OPT_PIS,
    OPT_PIS_COFINS_SEM_ICMS,
)
from custom_components.tarifas_aneel.coordinator import (
    AneelTarifasCoordinator,
    DadosAneel,
)
from custom_components.tarifas_aneel.models import (
    FonteDado,
    PostoTarifa,
    TarifaData,
)

TUSD = 0.66201
TE = 0.32459
ICMS_PCT = 17.0
PIS_PCT = 1.65
COFINS_PCT = 7.6
DIVISOR = (1 - 0.17) * (1 - 0.0165 - 0.076)

FILTRO = TarifaFiltro(
    distribuidora="EPDP",
    subgrupo="B1",
    modalidade="Convencional",
    classe="Residencial",
    subclasse="Residencial",
)


def _entry() -> MockConfigEntry:
    """Entry com o recorte da amostra e as alíquotas da revisão."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Tarifas EPDP — B1 • Convencional",
        data={
            CONF_DISTRIBUIDORA: "EPDP",
            CONF_SUBGRUPO: "B1",
            CONF_CLASSE: "Residencial",
            CONF_SUBCLASSE: "Residencial",
            CONF_MODALIDADE: "Convencional",
            CONF_DETALHE: "Não se aplica",
        },
        options={
            OPT_ICMS: ICMS_PCT,
            OPT_PIS: PIS_PCT,
            OPT_COFINS: COFINS_PCT,
            OPT_PIS_COFINS_SEM_ICMS: True,
        },
        entry_id="entry_calculo",
    )


def _dados() -> DadosAneel:
    """Payload com a tarifa da amostra (antes de impostos)."""
    return DadosAneel(
        filtro=FILTRO,
        tarifa=TarifaData(
            distribuidora="EPDP",
            subgrupo="B1",
            modalidade="Convencional",
            classe="Residencial",
            subclasse="Residencial",
            detalhe="Não se aplica",
            inicio_vigencia=date(2026, 7, 4),
            fim_vigencia=date(2027, 7, 3),
            postos={
                "Não se aplica": PostoTarifa(
                    posto="Não se aplica", tusd=TUSD, te=TE
                )
            },
            fonte=FonteDado.API,
        ),
        bandeira=None,
        fonte_tarifa=FonteDado.API,
        fonte_bandeira=None,
        calculos={},
    )


async def test_caso_numerico_no_coordinator(hass) -> None:
    """O coordinator aplica ICMS/PIS/COFINS e publica ≈ 1,3098 R$/kWh."""
    entry = _entry()
    entry.add_to_hass(hass)

    coordinator = AneelTarifasCoordinator(hass, entry, FILTRO)
    coordinator.data = _dados()

    coordinator.aplicar_opcoes()

    assert coordinator.data is not None
    calculo = coordinator.data.calculos["Não se aplica"]

    assert calculo.tarifa_tusd == pytest.approx(TUSD)
    assert calculo.tarifa_te == pytest.approx(TE)
    assert calculo.tarifa_sem_impostos == pytest.approx(0.98660)
    assert calculo.tarifa_com_impostos == pytest.approx(1.3098, abs=1e-4)
    assert calculo.tarifa_final == pytest.approx(1.3098, abs=1e-4)
    assert calculo.tarifa_final == pytest.approx(0.98660 / DIVISOR)
