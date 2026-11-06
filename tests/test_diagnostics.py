"""Testes do diagnóstico da integração no harness do Home Assistant.

Cobrem os cenários em que "Exportar diagnósticos" não pode levantar
exceção: sem dados, apenas cache e falha total (sem ``runtime_data``).
Também garantem que o coordinator exponha um timestamp próprio de
última atualização real, já que o HA 2024.10 não possui
``last_update_success_time`` no ``DataUpdateCoordinator``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

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
)
from custom_components.tarifas_aneel.coordinator import (
    AneelTarifasCoordinator,
    DadosAneel,
)
from custom_components.tarifas_aneel.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.tarifas_aneel.models import (
    BandeiraData,
    FonteDado,
    PostoTarifa,
    ResultadoCalculo,
    TarifaData,
)

FILTRO = TarifaFiltro(
    distribuidora="EMS",
    subgrupo="B1",
    modalidade="Convencional",
    classe="Residencial",
    subclasse="Residencial",
)

ULTIMA_REAL = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _entry() -> MockConfigEntry:
    """Config entry mínima usada pelo coordinator."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="EMS B1 Residencial",
        data={
            CONF_DISTRIBUIDORA: "EMS",
            CONF_SUBGRUPO: "B1",
            CONF_MODALIDADE: "Convencional",
            CONF_CLASSE: "Residencial",
            CONF_SUBCLASSE: "Residencial",
            CONF_DETALHE: "Não se aplica",
        },
        options={},
        entry_id="entry_diagnostico",
    )


def _tarifa() -> TarifaData:
    """Tarifa de teste em R$/kWh."""
    return TarifaData(
        distribuidora="EMS",
        subgrupo="B1",
        modalidade="Convencional",
        classe="Residencial",
        subclasse="Residencial",
        detalhe="Não se aplica",
        inicio_vigencia=date(2026, 7, 4),
        fim_vigencia=date(2027, 7, 3),
        postos={
            "Não se aplica": PostoTarifa(
                posto="Não se aplica", tusd=0.47242, te=0.31696
            )
        },
        fonte=FonteDado.API,
    )


def _bandeira() -> BandeiraData:
    """Bandeira de teste."""
    return BandeiraData(
        competencia=date(2026, 10, 1),
        nome="Verde",
        adicional_rsmwh=0.0,
        adicional=0.0,
        fonte=FonteDado.API,
    )


def _dados(
    fonte: FonteDado, ultima: datetime | None = ULTIMA_REAL
) -> DadosAneel:
    """Payload publicado pelo coordinator com a fonte informada."""
    return DadosAneel(
        filtro=FILTRO,
        tarifa=_tarifa(),
        bandeira=_bandeira(),
        fonte_tarifa=fonte,
        fonte_bandeira=fonte,
        ultima_atualizacao_real=ultima,
        calculos={
            "Não se aplica": ResultadoCalculo(
                tarifa_te=0.31696,
                tarifa_tusd=0.47242,
                tarifa_sem_impostos=0.78938,
                adicional_bandeira=0.0,
                tarifa_com_bandeira=0.78938,
                tarifa_com_impostos=0.78938,
                tarifa_final=0.78938,
            )
        },
    )


async def test_diagnostico_sem_dados_nao_levanta(hass) -> None:
    """Coordinator sem dados ainda exporta o diagnóstico da entry."""
    entry = _entry()
    entry.runtime_data = AneelTarifasCoordinator(hass, entry, FILTRO)

    resultado = await async_get_config_entry_diagnostics(hass, entry)

    assert resultado["entry"]["data"][CONF_DISTRIBUIDORA] == "EMS"
    # Sem dados do coordinator, o bloco correspondente é omitido.
    assert "coordinator" not in resultado


async def test_diagnostico_somente_cache_nao_levanta(hass) -> None:
    """Com apenas cache, o diagnóstico usa o timestamp próprio."""
    entry = _entry()
    coordinator = AneelTarifasCoordinator(hass, entry, FILTRO)
    coordinator.data = _dados(FonteDado.CACHE)
    entry.runtime_data = coordinator

    resultado = await async_get_config_entry_diagnostics(hass, entry)

    diagnostico = resultado["coordinator"]
    assert diagnostico["fonte_tarifa"] == "Cache"
    assert diagnostico["fonte_bandeira"] == "Cache"
    assert diagnostico["ultima_atualizacao_sucesso"] == ULTIMA_REAL.isoformat()
    assert diagnostico["ultima_atualizacao_real"] == ULTIMA_REAL.isoformat()


async def test_diagnostico_falha_total_nao_levanta(hass) -> None:
    """Entry sem ``runtime_data`` (setup falhou) não quebra o diagnóstico."""
    entry = _entry()

    resultado = await async_get_config_entry_diagnostics(hass, entry)

    assert resultado["entry"]["data"][CONF_DISTRIBUIDORA] == "EMS"
    assert "coordinator" not in resultado


async def test_diagnostico_api_expoe_timestamp_do_coordinator(hass) -> None:
    """O coordinator guarda a última atualização real fora do payload."""
    entry = _entry()
    coordinator = AneelTarifasCoordinator(hass, entry, FILTRO)
    coordinator.data = _dados(FonteDado.API)
    entry.runtime_data = coordinator

    assert coordinator.ultima_atualizacao_real == ULTIMA_REAL

    resultado = await async_get_config_entry_diagnostics(hass, entry)

    diagnostico = resultado["coordinator"]
    assert diagnostico["fonte_tarifa"] == "API"
    assert diagnostico["ultima_atualizacao_real"] == ULTIMA_REAL.isoformat()
