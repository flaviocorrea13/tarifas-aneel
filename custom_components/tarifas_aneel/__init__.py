"""Integração Tarifas ANEEL.

Configura tarifas de aplicação (TUSD/TE) e bandeiras tarifárias das
distribuidoras brasileiras a partir do Portal de Dados Abertos da ANEEL,
calcula o preço final com impostos (gross-up "por dentro") e expõe
entidades compatíveis com o painel de Energia.

Uma entry = um recorte tarifário (distribuidora + subgrupo + classe +
subclasse + modalidade + detalhe). O coordinator vive em
``entry.runtime_data``.

Inicialização rápida: o cache persistente é publicado antes das
plataformas (``fonte_dado = Cache``) e a busca real (API -> CSV) roda em
segundo plano, sem segurar o setup. Só na primeira instalação, sem cache,
o setup espera ``async_config_entry_first_refresh``.

Mudanças de opções que não trocam as entidades de consumo/injeção são
reaplicadas em memória (sem rede e sem recarregar a entry). Quando as
entidades mudam, a entry é recarregada — o coordinator reaproveita o
último payload em memória, então o reload também não faz chamadas HTTP.
"""

from __future__ import annotations

import logging
from typing import Any, Final

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
    DOMAIN,
)
from custom_components.tarifas_aneel.coordinator import (
    AneelTarifasCoordinator,
    DadosAneel,
)

_LOGGER: Final = logging.getLogger(__name__)

PLATFORMS: Final = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]

# Payload guardado no unload para o setup seguinte reaproveitar sem rede.
CHAVE_DADOS_RELOAD: Final = "dados_reload"


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


def _guardar_dados_reload(
    hass: HomeAssistant, entry_id: str, dados: DadosAneel
) -> None:
    """Guarda o último payload em memória para o próximo setup."""
    hass.data.setdefault(DOMAIN, {})[f"{CHAVE_DADOS_RELOAD}_{entry_id}"] = dados


def _retirar_dados_reload(
    hass: HomeAssistant, entry_id: str
) -> DadosAneel | None:
    """Recupera (e remove) o payload guardado no unload."""
    guardados: dict[str, Any] = hass.data.get(DOMAIN, {})
    dados = guardados.pop(f"{CHAVE_DADOS_RELOAD}_{entry_id}", None)
    return dados if isinstance(dados, DadosAneel) else None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura a entry: coordinator + plataformas."""
    coordinator = AneelTarifasCoordinator(hass, entry, _filtro_da_entry(entry))
    entry.runtime_data = coordinator

    dados_reload = _retirar_dados_reload(hass, entry.entry_id)
    if dados_reload is not None:
        # Reload (ex.: troca das entidades de consumo/injeção): reaproveita
        # o payload em memória e não chama a ANEEL.
        coordinator.async_set_updated_data(dados_reload)
        _LOGGER.debug(
            "Payload em memória reaproveitado no setup de %s (sem rede)",
            entry.entry_id,
        )
    elif await coordinator.async_carregar_cache_inicial():
        # Cache publicado: as entidades já nascem com dado; a busca real
        # roda em segundo plano e atualiza o estado ao terminar.
        entry.async_create_background_task(
            hass,
            coordinator.async_refresh(),
            f"{DOMAIN}_refresh_{entry.entry_id}",
        )
    else:
        # Primeira instalação (sem cache): mantém o comportamento antigo.
        # Se as 3 camadas falharem, o HA entra em retry com backoff.
        await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_opcoes_atualizadas))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Descarrega as plataformas e guarda o payload para o reload."""
    coordinator = getattr(entry, "runtime_data", None)
    dados = coordinator.data if coordinator is not None else None
    if isinstance(dados, DadosAneel):
        _guardar_dados_reload(hass, entry.entry_id, dados)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Limpa o payload guardado quando a entry é removida de vez."""
    guardados: dict[str, Any] = hass.data.get(DOMAIN, {})
    guardados.pop(f"{CHAVE_DADOS_RELOAD}_{entry.entry_id}", None)


async def _async_opcoes_atualizadas(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Aplica novas opções sem rede quando possível.

    Alíquotas, CIP/COSIP, intervalo, dia de leitura e janela de ponta só
    afetam o cálculo: o coordinator recalcula sobre os dados em memória.
    A entry só é recarregada quando as entidades de consumo/injeção mudam
    (o sensor de custo precisa ser criado/recriado); mesmo nesse caso o
    payload em memória é reaproveitado, sem chamadas HTTP.
    """
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None or coordinator.opcoes_entidades_alteradas:
        await hass.config_entries.async_reload(entry.entry_id)
        return
    coordinator.aplicar_opcoes()
