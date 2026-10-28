"""Binary sensor de dados desatualizados da integração Tarifas ANEEL.

Ligado quando a última atualização REAL (API ou CSV) tem mais de
``STALE_DATA_DAYS`` (3 dias) — sinaliza que o recorte está sendo servido
apenas do cache persistente ou que nunca chegou dado real.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from custom_components.tarifas_aneel.const import STALE_DATA_DAYS
from custom_components.tarifas_aneel.coordinator import AneelTarifasCoordinator
from custom_components.tarifas_aneel.entity import AneelBaseEntity

LIMITE_STALE: Final = timedelta(days=STALE_DATA_DAYS)


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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Cria o binary sensor da entry."""
    coordinator: AneelTarifasCoordinator = entry.runtime_data
    async_add_entities([DadosDesatualizadosBinarySensor(coordinator, entry)])
