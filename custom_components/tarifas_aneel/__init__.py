"""Integração Tarifas ANEEL.

Configura tarifas de aplicação (TUSD/TE) e bandeiras tarifárias das
distribuidoras brasileiras a partir do Portal de Dados Abertos da ANEEL,
calcula o preço final com impostos (gross-up "por dentro") e expõe
entidades compatíveis com o painel de Energia.

Uma entry = um recorte tarifário (distribuidora + subgrupo + classe +
subclasse + modalidade + detalhe). O coordinator vive em
``entry.runtime_data``; mudanças de opções recarregam a entry (as alíquotas
e o intervalo afetam o cálculo e o ciclo de atualização).
"""

from __future__ import annotations

from typing import Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from custom_components.tarifas_aneel.api import TarifaFiltro
from custom_components.tarifas_aneel.const import (
    CONF_CLASSE,
    CONF_DETALHE,
    CONF_DISTRIBUIDORA,
    CONF_MODALIDADE,
    CONF_SUBCLASSE,
    CONF_SUBGRUPO,
    DEFAULT_DETALHE,
)
from custom_components.tarifas_aneel.coordinator import AneelTarifasCoordinator

PLATFORMS: Final = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]


def _filtro_da_entry(entry: ConfigEntry) -> TarifaFiltro:
    """Reconstrói o TarifaFiltro persistido no data da entry."""
    return TarifaFiltro(
        distribuidora=str(entry.data[CONF_DISTRIBUIDORA]),
        subgrupo=str(entry.data[CONF_SUBGRUPO]),
        modalidade=str(entry.data[CONF_MODALIDADE]),
        classe=str(entry.data[CONF_CLASSE]),
        subclasse=str(entry.data[CONF_SUBCLASSE]),
        detalhe=str(entry.data.get(CONF_DETALHE, DEFAULT_DETALHE)),
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura a entry: coordinator + plataformas."""
    coordinator = AneelTarifasCoordinator(hass, entry, _filtro_da_entry(entry))
    # Se as 3 camadas falharem sem cache (UpdateFailed), o HA entra em
    # retry com backoff — comportamento desejado para "sem dado nenhum".
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_opcoes_atualizadas))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Descarrega as plataformas da entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_opcoes_atualizadas(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Recarrega a entry quando o usuário altera opções.

    Alíquotas, intervalo e janela de ponta afetam o cálculo e o ciclo do
    coordinator; o reload garante estado consistente (padrão documentado
    para options flow sem ``OptionsFlowWithReload``).
    """
    await hass.config_entries.async_reload(entry.entry_id)
