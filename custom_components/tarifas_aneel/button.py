"""Botão de atualização manual da integração Tarifas ANEEL.

Força um ciclo imediato do coordinator (JSON -> CSV -> cache). Útil
durante a troca de vigência da tarifa ou para re-tentar após uma queda
da ANEEL sem esperar o próximo intervalo.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.tarifas_aneel.coordinator import AneelTarifasCoordinator
from custom_components.tarifas_aneel.entity import AneelBaseEntity


class AtualizarAgoraButton(AneelBaseEntity, ButtonEntity):
    """Força uma atualização imediata dos dados do recorte."""

    _attr_device_class = ButtonDeviceClass.UPDATE
    _attr_translation_key = "atualizar_agora"

    def __init__(
        self, coordinator: AneelTarifasCoordinator, entry: ConfigEntry
    ) -> None:
        """Inicializa o botão."""
        super().__init__(coordinator, entry, "atualizar_agora")

    async def async_press(self) -> None:
        """Aciona uma atualização do coordinator (push nas entidades)."""
        await self.coordinator.async_request_refresh()


class LimparCacheAtualizarButton(AneelBaseEntity, ButtonEntity):
    """Remove o cache persistente e força uma busca real (diagnóstico)."""

    _attr_icon = "mdi:database-refresh"
    _attr_translation_key = "limpar_cache_atualizar"

    def __init__(
        self, coordinator: AneelTarifasCoordinator, entry: ConfigEntry
    ) -> None:
        """Inicializa o botão de limpeza do cache."""
        super().__init__(coordinator, entry, "limpar_cache_atualizar")

    async def async_press(self) -> None:
        """Apaga o cache persistente e atualiza imediatamente."""
        await self.coordinator.async_limpar_cache()
        await self.coordinator.async_refresh()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Cria os botões da entry."""
    coordinator: AneelTarifasCoordinator = entry.runtime_data
    async_add_entities(
        [
            AtualizarAgoraButton(coordinator, entry),
            LimparCacheAtualizarButton(coordinator, entry),
        ]
    )
