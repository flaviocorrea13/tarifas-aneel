"""Binary sensors da integração Tarifas ANEEL.

Além do aviso de dados desatualizados, a integração expõe o estado da
origem em tempo real e um indicador de bandeira vermelha, úteis para
automações e para o diagnóstico do fallback (API → CSV → cache).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Final

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from custom_components.tarifas_aneel.const import (
    BANDEIRA_VERMELHA_P1,
    BANDEIRA_VERMELHA_P2,
    STALE_DATA_DAYS,
)
from custom_components.tarifas_aneel.coordinator import AneelTarifasCoordinator
from custom_components.tarifas_aneel.entity import AneelBaseEntity
from custom_components.tarifas_aneel.models import FonteDado

LIMITE_STALE: Final = timedelta(days=STALE_DATA_DAYS)
BANDEIRAS_VERMELHAS: Final = frozenset(
    {BANDEIRA_VERMELHA_P1, BANDEIRA_VERMELHA_P2}
)


class DadosDesatualizadosBinarySensor(AneelBaseEntity, BinarySensorEntity):
    """Sinaliza dados servidos só do cache ou sem dado real nenhum."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "dados_desatualizados"

    def __init__(
        self, coordinator: AneelTarifasCoordinator, entry: ConfigEntry
    ) -> None:
        """Inicializa o binary sensor."""
        super().__init__(coordinator, entry, "dados_desatualizados")

    @property
    def is_on(self) -> bool:
        """Ligado quando a última atualização real excede o limite."""
        dados = self._dados
        if dados is None or dados.ultima_atualizacao_real is None:
            # Nunca chegou dado real (todas as camadas falharam de início):
            # por definição, a situação é desatualizada.
            return True
        return (dt_util.utcnow() - dados.ultima_atualizacao_real) > LIMITE_STALE


class StatusApiBinarySensor(AneelBaseEntity, BinarySensorEntity):
    """Ligado quando tarifa e bandeira vieram da API (tempo real).

    CSV e cache são fallback: nesses casos o sensor fica desligado, e os
    atributos mostram a origem de cada item separadamente.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_icon = "mdi:cloud-check-outline"
    _attr_translation_key = "status_api"

    def __init__(
        self, coordinator: AneelTarifasCoordinator, entry: ConfigEntry
    ) -> None:
        """Inicializa o sensor de status da API."""
        super().__init__(coordinator, entry, "status_api")

    @property
    def is_on(self) -> bool:
        """Ligado apenas quando os dois itens vieram da camada API."""
        dados = self._dados
        if dados is None:
            return False
        return (
            dados.fonte_tarifa is FonteDado.API
            and dados.fonte_bandeira is FonteDado.API
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Origem de cada item para explicar um estado desligado."""
        dados = self._dados
        if dados is None:
            return {}
        return {
            "fonte_tarifa": (
                dados.fonte_tarifa.value
                if dados.fonte_tarifa is not None
                else None
            ),
            "fonte_bandeira": (
                dados.fonte_bandeira.value
                if dados.fonte_bandeira is not None
                else None
            ),
        }


class BandeiraVermelhaBinarySensor(AneelBaseEntity, BinarySensorEntity):
    """Ligado quando a bandeira vigente é Vermelha P1 ou P2."""

    _attr_icon = "mdi:flag"
    _attr_translation_key = "bandeira_vermelha_ativa"

    def __init__(
        self, coordinator: AneelTarifasCoordinator, entry: ConfigEntry
    ) -> None:
        """Inicializa o sensor de bandeira vermelha."""
        super().__init__(coordinator, entry, "bandeira_vermelha_ativa")

    @property
    def _bandeira(self) -> str | None:
        """Nome da bandeira vigente (``None`` sem dado)."""
        dados = self._dados
        if dados is None or dados.bandeira is None:
            return None
        return dados.bandeira.nome

    @property
    def available(self) -> bool:
        """Indisponível enquanto não houver bandeira carregada."""
        return super().available and self._bandeira is not None

    @property
    def is_on(self) -> bool:
        """Ligado para Vermelha P1/P2; desligado nas demais bandeiras."""
        return self._bandeira in BANDEIRAS_VERMELHAS

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Bandeira atual e adicional em R$/kWh."""
        dados = self._dados
        if dados is None or dados.bandeira is None:
            return {}
        return {
            "bandeira": dados.bandeira.nome,
            "adicional_rskwh": round(dados.bandeira.adicional, 5),
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Cria os binary sensors da entry."""
    coordinator: AneelTarifasCoordinator = entry.runtime_data
    async_add_entities(
        [
            DadosDesatualizadosBinarySensor(coordinator, entry),
            StatusApiBinarySensor(coordinator, entry),
            BandeiraVermelhaBinarySensor(coordinator, entry),
        ]
    )
