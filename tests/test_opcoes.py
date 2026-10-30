"""Testes do options flow e da reaplicação de opções sem rede.

Não usa o harness do Home Assistant: monta objetos mínimos (entry,
coordinator e hass) para verificar o contrato do setup:

* mudar alíquotas recalcula em memória, sem recarregar a entry e sem
  chamar a API;
* trocar as entidades de consumo/injeção pede reload (para criar/remover
  o sensor de custo);
* os seletores de consumo/injeção filtram sensores de energia.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

from homeassistant.helpers import selector
import pytest

from custom_components.tarifas_aneel.api import TarifaFiltro
from custom_components.tarifas_aneel.config_flow import (
    OptionsFlowTarifas,
    _validar_entidades,
)
from custom_components.tarifas_aneel.const import (
    OPT_CONSUMO_ENTITY_ID,
    OPT_DIA_LEITURA,
    OPT_ICMS,
    OPT_INJECAO_ENTITY_ID,
    OPT_UPDATE_INTERVAL,
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

FILTRO = TarifaFiltro(
    distribuidora="EPDP",
    subgrupo="B1",
    modalidade="Convencional",
    classe="Residencial",
    subclasse="Residencial",
)


def _tarifa() -> TarifaData:
    """Tarifa fixa de 0,98660 R$/kWh (TUSD 0,66201 + TE 0,32459)."""
    return TarifaData(
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
                posto="Não se aplica", tusd=0.66201, te=0.32459
            )
        },
        fonte=FonteDado.API,
    )


def _dados() -> DadosAneel:
    """Payload em memória como se tivesse vindo da API."""
    return DadosAneel(
        filtro=FILTRO,
        tarifa=_tarifa(),
        bandeira=None,
        fonte_tarifa=FonteDado.API,
        fonte_bandeira=None,
        calculos={},
    )


def _coordinator(opcoes: dict[str, Any]) -> AneelTarifasCoordinator:
    """Coordinator real sem ``__init__`` (sem loop/Store) para testar cálculo."""
    entry = SimpleNamespace(
        entry_id="entry_teste", options=dict(opcoes), data={}
    )
    coordinator = object.__new__(AneelTarifasCoordinator)
    coordinator._entry = entry
    coordinator._filtro = FILTRO
    coordinator.update_interval = None
    coordinator._opcoes_entidades = coordinator._entidades_opcoes()
    coordinator.data = _dados()
    # Substitui o agendamento/listeners do DataUpdateCoordinator.
    coordinator.async_set_updated_data = lambda dados: setattr(
        coordinator, "data", dados
    )
    return coordinator


def test_validar_entidades_iguais() -> None:
    """Consumo e injeção não podem ser a mesma entidade."""
    assert _validar_entidades("sensor.energia", "sensor.energia") == (
        "entidades_iguais"
    )
    assert _validar_entidades("sensor.consumo", "sensor.injecao") is None
    assert _validar_entidades("sensor.consumo", None) is None
    assert _validar_entidades(None, "sensor.injecao") is None
    assert _validar_entidades("", "") is None


def _como_lista(valor: Any) -> list[Any]:
    """Normaliza o filtro do seletor (o HA pode devolver lista ou string)."""
    if isinstance(valor, (list, tuple, set)):
        return list(valor)
    return [valor]


def test_seletores_de_energia_e_dia_de_leitura() -> None:
    """Options flow: seletores de energia e campo de dia (1..28)."""
    flow = OptionsFlowTarifas(
        SimpleNamespace(
            entry_id="entry_teste",
            options={},
            data={"modalidade": "Convencional"},
        )
    )
    campos = {
        marcador.schema: seletor
        for marcador, seletor in flow._esquema().schema.items()
    }

    for chave in (OPT_CONSUMO_ENTITY_ID, OPT_INJECAO_ENTITY_ID):
        seletor_entidade = campos[chave]
        assert isinstance(seletor_entidade, selector.EntitySelector)
        # O HA normaliza os filtros do seletor para lista.
        assert "sensor" in _como_lista(seletor_entidade.config["domain"])
        assert "energy" in _como_lista(seletor_entidade.config["device_class"])

    dia = campos[OPT_DIA_LEITURA]
    assert isinstance(dia, selector.NumberSelector)
    assert dia.config["min"] == 1
    assert dia.config["max"] == 28


def test_aplicar_opcoes_recalcula_em_memoria_sem_rede() -> None:
    """Mudar alíquotas refaz o cálculo com os dados em memória."""
    coordinator = _coordinator({OPT_ICMS: 0})
    coordinator.aplicar_opcoes()
    assert coordinator.data is not None
    calculo = coordinator.data.calculos["Não se aplica"]
    assert calculo.tarifa_final == pytest.approx(0.98660)

    # Simula o que o HA faz antes de chamar o listener: atualiza options.
    coordinator._entry.options = {
        OPT_ICMS: 17.0,
        "pis_percentual": 1.65,
        "cofins_percentual": 7.6,
        OPT_UPDATE_INTERVAL: 24,
    }
    # Qualquer chamada de rede derrubaria o teste.
    coordinator._async_update_data = _nao_deve_chamar_rede  # type: ignore[method-assign]

    coordinator.aplicar_opcoes()

    assert coordinator.update_interval == timedelta(hours=24)
    calculo = coordinator.data.calculos["Não se aplica"]
    assert calculo.tarifa_final == pytest.approx(1.309834, abs=1e-5)


async def _nao_deve_chamar_rede() -> DadosAneel:
    """Guarda-corpo: o caminho em memória não deve buscar dados."""
    msg = "chamada de rede inesperada ao reaplicar opções"
    raise AssertionError(msg)


class _ConfigEntriesFake:
    """Registra chamadas de ``async_reload``."""

    def __init__(self) -> None:
        self.recarregadas: list[str] = []

    async def async_reload(self, entry_id: str) -> None:
        self.recarregadas.append(entry_id)


def test_listener_nao_recarrega_quando_so_muda_imposto() -> None:
    """Listener aplica em memória e não recarrega a entry."""
    coordinator = _coordinator({OPT_ICMS: 0})
    coordinator._entry.options = {OPT_ICMS: 17.0}
    hass = SimpleNamespace(config_entries=_ConfigEntriesFake())
    entry = SimpleNamespace(entry_id="entry_teste", runtime_data=coordinator)

    from custom_components.tarifas_aneel import _async_opcoes_atualizadas

    asyncio.run(_async_opcoes_atualizadas(hass, entry))

    assert hass.config_entries.recarregadas == []
    assert coordinator.data.calculos["Não se aplica"].tarifa_final == (
        pytest.approx(0.98660 / 0.83)
    )


def test_listener_recarrega_quando_troca_entidade() -> None:
    """Trocar consumo/injeção exige reload (cria/remove o sensor de custo)."""
    coordinator = _coordinator({OPT_CONSUMO_ENTITY_ID: "sensor.consumo_antigo"})
    coordinator._entry.options = {
        OPT_CONSUMO_ENTITY_ID: "sensor.consumo_novo",
    }
    hass = SimpleNamespace(config_entries=_ConfigEntriesFake())
    entry = SimpleNamespace(entry_id="entry_teste", runtime_data=coordinator)

    from custom_components.tarifas_aneel import _async_opcoes_atualizadas

    asyncio.run(_async_opcoes_atualizadas(hass, entry))

    assert hass.config_entries.recarregadas == ["entry_teste"]
