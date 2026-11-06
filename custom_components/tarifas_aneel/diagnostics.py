"""Diagnósticos da integração Tarifas ANEEL.

Monta o payload exibido em Configurações → Integrações → Diagnóstico:
recorte configurado, opções e o estado corrente do coordinator (tarifa,
bandeira, fonte de cada dado e cálculos por posto).

A integração não guarda credenciais; a redação padrão fica por convenção,
caso alguma chave sensível apareça no futuro no data da entry.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import logging
from typing import TYPE_CHECKING, Any, Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import async_redact_data

from custom_components.tarifas_aneel.coordinator import AneelTarifasCoordinator

if TYPE_CHECKING:
    from custom_components.tarifas_aneel.coordinator import DadosAneel

_LOGGER: Final = logging.getLogger(__name__)

# Não há dados sensíveis neste payload; chaves padrão por convenção.
TO_REDACT: Final = {"entry_title"}


def _iso(valor: Any) -> str | None:
    """Formata um ``datetime`` em ISO; ignora qualquer outro tipo."""
    return valor.isoformat() if isinstance(valor, datetime) else None


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
        try:
            payload["coordinator"] = _diagnosticos_do_coordinator(
                coordinator, coordinator.data
            )
        except Exception as err:
            # O recurso existe justamente para investigar problemas: uma
            # falha aqui esconderia o próprio estado que se quer reportar.
            _LOGGER.exception("Falha ao montar o diagnóstico da entry")
            payload["coordinator_error"] = type(err).__name__
    return payload


def _diagnosticos_do_coordinator(
    coordinator: AneelTarifasCoordinator,
    dados: DadosAneel,
) -> dict[str, Any]:
    """Serializa o estado corrente do coordinator."""
    intervalo = getattr(coordinator, "update_interval", None)

    # HA >= 2024.11 expõe ``last_update_success_time``; a versão mínima
    # (2024.10) não. Nesse caso usamos o timestamp próprio do coordinator,
    # que também sobrevive a reinícios via cache.
    ultima_sucesso = getattr(coordinator, "last_update_success_time", None)
    if not isinstance(ultima_sucesso, datetime):
        ultima_sucesso = getattr(coordinator, "ultima_atualizacao_real", None)
    if not isinstance(ultima_sucesso, datetime):
        ultima_sucesso = dados.ultima_atualizacao_real

    ultima_real = getattr(coordinator, "ultima_atualizacao_real", None)
    if not isinstance(ultima_real, datetime):
        ultima_real = dados.ultima_atualizacao_real

    return {
        "intervalo_atualizacao_horas": (
            round(intervalo.total_seconds() / 3600, 2) if intervalo else None
        ),
        "ultima_atualizacao_sucesso": _iso(ultima_sucesso),
        "ultima_atualizacao_real": _iso(ultima_real),
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
