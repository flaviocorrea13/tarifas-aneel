"""Diagnósticos da integração Tarifas ANEEL.

Monta o payload exibido em Configurações → Integrações → Diagnóstico:
recorte configurado, opções e o estado corrente do coordinator (tarifa,
bandeira, fonte de cada dado e cálculos por posto).

A integração não guarda credenciais; a redação padrão fica por convenção,
caso alguma chave sensível apareça no futuro no data da entry.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import async_redact_data

from custom_components.tarifas_aneel.coordinator import AneelTarifasCoordinator

if TYPE_CHECKING:
    from custom_components.tarifas_aneel.coordinator import DadosAneel

# Não há dados sensíveis neste payload; chaves padrão por convenção.
TO_REDACT: Final = {"entry_title"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Retorna o diagnóstico da entry (recorte, opções e coordinator)."""
    payload: dict[str, Any] = {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
    }
    coordinator = getattr(entry, "runtime_data", None)
    if (
        isinstance(coordinator, AneelTarifasCoordinator)
        and coordinator.data is not None
    ):
        payload["coordinator"] = _diagnosticos_do_coordinator(
            coordinator, coordinator.data
        )
    return payload


def _diagnosticos_do_coordinator(
    coordinator: AneelTarifasCoordinator,
    dados: DadosAneel,
) -> dict[str, Any]:
    """Serializa o estado corrente do coordinator."""
    intervalo = coordinator.update_interval
    return {
        "intervalo_atualizacao_horas": (
            round(intervalo.total_seconds() / 3600, 2) if intervalo else None
        ),
        "ultima_atualizacao_sucesso": (
            coordinator.last_update_success_time.isoformat()
            if coordinator.last_update_success_time
            else None
        ),
        "ultima_atualizacao_real": (
            dados.ultima_atualizacao_real.isoformat()
            if dados.ultima_atualizacao_real
            else None
        ),
        "fonte_tarifa": (
            dados.fonte_tarifa.value if dados.fonte_tarifa else None
        ),
        "fonte_bandeira": (
            dados.fonte_bandeira.value if dados.fonte_bandeira else None
        ),
        "tarifa": dados.tarifa.to_dict() if dados.tarifa else None,
        "bandeira": dados.bandeira.to_dict() if dados.bandeira else None,
        "calculos": {
            posto: asdict(calculo)
            for posto, calculo in dados.calculos.items()
        },
    }
