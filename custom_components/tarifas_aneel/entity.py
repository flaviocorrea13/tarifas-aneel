"""Entidade base comum às plataformas da integração Tarifas ANEEL.

Centraliza o que é igual para todas as entidades da entry: vínculo com o
coordinator (``CoordinatorEntity``), ``unique_id`` estável, ``DeviceInfo``,
``has_entity_name`` e os atributos padrão de diagnóstico.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.tarifas_aneel.const import (
    ANEEL_BASE_URL,
    ATTR_ALIQUOTAS_APLICADAS,
    ATTR_ALIQUOTAS_REVISADAS_EM,
    ATTR_DATA_COMPETENCIA,
    ATTR_DISTRIBUIDORA,
    ATTR_FONTE_DADO,
    ATTR_IMPOSTOS_CONFIGURADOS,
    ATTR_MODALIDADE,
    ATTR_PIS_COFINS_SEM_ICMS,
    ATTR_SUBGRUPO,
    CONF_DISTRIBUIDORA,
    CONF_MODALIDADE,
    CONF_SUBGRUPO,
    DEFAULT_COFINS,
    DEFAULT_ICMS,
    DEFAULT_PIS,
    DEFAULT_PIS_COFINS_SEM_ICMS,
    DEVICE_MANUFACTURER,
    DISTRIBUTOR_NAMES,
    DOMAIN,
    OPT_ALIQUOTAS_REVISADAS_EM,
    OPT_COFINS,
    OPT_ICMS,
    OPT_PIS,
    OPT_PIS_COFINS_SEM_ICMS,
)
from custom_components.tarifas_aneel.coordinator import AneelTarifasCoordinator

if TYPE_CHECKING:
    from custom_components.tarifas_aneel.coordinator import DadosAneel
    from custom_components.tarifas_aneel.models import FonteDado


class AneelBaseEntity(CoordinatorEntity[AneelTarifasCoordinator]):
    """Base comum: device, unique_id, atributos padrão e helpers."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AneelTarifasCoordinator,
        entry: ConfigEntry,
        unique_suffix: str,
    ) -> None:
        """Inicializa com device info e unique_id derivados da entry."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{unique_suffix}"
        sigla = str(entry.data.get(CONF_DISTRIBUIDORA, ""))
        nome = DISTRIBUTOR_NAMES.get(sigla, sigla) or "Tarifas ANEEL"
        # O dicionário carrega a UF entre parênteses ("Energisa Mato Grosso
        # do Sul (MS)"); no nome do dispositivo usamos só o nome amigável.
        if nome.endswith(")") and " (" in nome:
            nome = nome.rsplit(" (", 1)[0]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer=DEVICE_MANUFACTURER,
            name=nome,
            model=(
                f"{entry.data.get(CONF_SUBGRUPO, '')} • "
                f"{entry.data.get(CONF_MODALIDADE, '')}"
            ).strip(" •"),
            configuration_url=ANEEL_BASE_URL,
        )

    @property
    def _dados(self) -> DadosAneel | None:
        """Dados correntes publicados pelo coordinator."""
        return self.coordinator.data

    def _atributos_padrao(self, fonte: FonteDado | None) -> dict[str, Any]:
        """Atributos comuns de diagnóstico (recorte, fonte e alíquotas)."""
        dados = self._dados
        if dados is None:
            return {}
        atributos: dict[str, Any] = {
            ATTR_DISTRIBUIDORA: dados.filtro.distribuidora,
            ATTR_SUBGRUPO: dados.filtro.subgrupo,
            ATTR_MODALIDADE: dados.filtro.modalidade,
            ATTR_ALIQUOTAS_APLICADAS: self._aliquotas_pct(),
        }
        if fonte is not None:
            atributos[ATTR_FONTE_DADO] = fonte.value
        if dados.bandeira is not None:
            atributos[ATTR_DATA_COMPETENCIA] = (
                dados.bandeira.competencia.isoformat()
            )
        return atributos

    def _aliquotas_pct(self) -> dict[str, float]:
        """Alíquotas configuradas nas opções, em percentual (18 = 18%)."""
        opcoes = self._entry.options

        def pct(chave: str, padrao: float) -> float:
            try:
                return round(float(opcoes.get(chave, padrao)), 2)
            except (TypeError, ValueError):
                return padrao

        return {
            "icms": pct(OPT_ICMS, DEFAULT_ICMS),
            "pis": pct(OPT_PIS, DEFAULT_PIS),
            "cofins": pct(OPT_COFINS, DEFAULT_COFINS),
        }

    def _atributos_impostos(self) -> dict[str, Any]:
        """Atributos de configuração e revisão dos impostos.

        ``impostos_configurados`` é ``False`` quando ICMS, PIS e COFINS
        estão todos em zero (o preço final mostrado é a tarifa sem
        impostos). ``aliquotas_revisadas_em`` é a data (ISO) em que as
        alíquotas foram salvas pela última vez no options flow.
        """
        opcoes = self._entry.options
        aliquotas = self._aliquotas_pct()
        return {
            ATTR_IMPOSTOS_CONFIGURADOS: any(
                abs(valor) > 1e-9 for valor in aliquotas.values()
            ),
            ATTR_ALIQUOTAS_REVISADAS_EM: opcoes.get(
                OPT_ALIQUOTAS_REVISADAS_EM
            ),
            ATTR_PIS_COFINS_SEM_ICMS: bool(
                opcoes.get(
                    OPT_PIS_COFINS_SEM_ICMS,
                    DEFAULT_PIS_COFINS_SEM_ICMS,
                )
            ),
        }
