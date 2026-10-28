"""Sensores da integração Tarifas ANEEL.

O sensor ``tarifa_final`` é a entidade de preço para o painel de Energia:
na modalidade Branca ele acompanha o posto tarifário ativo (Ponta,
Intermediário, Fora ponta). Nenhuma regra de cálculo vive aqui — os
valores vêm de ``ResultadoCalculo`` (calc.py) via coordinator.

Padrão da entidade de preço: como o sensor de preço do Tibber (referência
do painel de Energia), usamos ``state_class: measurement`` e unidade
``BRL/kWh`` **sem** ``device_class`` — ``monetary`` forçaria
``state_class: total`` (``DEVICE_CLASS_STATE_CLASSES``), que é a semântica
errada para um preço pontual e pode distorcer o custo calculado pelo
painel de Energia.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Final

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from custom_components.tarifas_aneel.const import (
    ATTR_POSTO_TARIFARIO,
    ATTR_TARIFA_POR_POSTO,
    CONF_MODALIDADE,
    DEFAULT_CIP_COSIP,
    MODALIDADE_BRANCA,
    OPT_CIP_COSIP,
    UNIT_PRECO_ENERGIA,
    UNIT_REAIS,
)
from custom_components.tarifas_aneel.coordinator import AneelTarifasCoordinator
from custom_components.tarifas_aneel.entity import AneelBaseEntity
from custom_components.tarifas_aneel.models import ResultadoCalculo

# O posto tarifário muda em horários cheios; uma verificação leve a cada
# 5 min garante que o estado troque perto da virada (a troca em si só
# acontece quando o posto realmente muda).
INTERVALO_POSTO: Final = timedelta(minutes=5)


class TarifaSensor(AneelBaseEntity, SensorEntity):
    """Sensor numérico de tarifa (um campo de ResultadoCalculo, R$/kWh)."""

    _attr_native_unit_of_measurement = UNIT_PRECO_ENERGIA
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 5
    _campo: str = ""

    def __init__(
        self,
        coordinator: AneelTarifasCoordinator,
        entry: ConfigEntry,
        unique_suffix: str,
    ) -> None:
        """Inicializa e agenda verificação periódica do posto."""
        super().__init__(coordinator, entry, unique_suffix)
        self._attr_translation_key = unique_suffix
        self._cancelador: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        """Registra verificação periódica do posto (afeta só a Branca)."""
        await super().async_added_to_hass()
        self._cancelador = async_track_time_interval(
            self.hass, self._ao_mudar_periodo, INTERVALO_POSTO
        )

    async def async_will_remove_from_hass(self) -> None:
        """Cancela a verificação periódica."""
        if self._cancelador is not None:
            self._cancelador()
            self._cancelador = None

    @callback
    def _ao_mudar_periodo(self, agora: datetime) -> None:
        """Reescreve o estado quando o posto ativo pode ter mudado."""
        if self._eh_branca():
            self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Helpers de posto/dados
    # ------------------------------------------------------------------
    def _eh_branca(self) -> bool:
        """Modalidade da entry é Branca."""
        dados = self._dados
        return (
            dados is not None
            and dados.tarifa is not None
            and dados.tarifa.modalidade == MODALIDADE_BRANCA
        )

    def _posto_atual(self) -> str | None:
        """Posto do momento (na Convencional, o único posto do recorte)."""
        dados = self._dados
        if dados is None or dados.tarifa is None:
            return None
        if dados.tarifa.modalidade != MODALIDADE_BRANCA:
            return next(iter(dados.tarifa.postos), None)
        return self.coordinator.posto_ativo(dt_util.now())

    def _calculo_atual(self) -> ResultadoCalculo | None:
        """ResultadoCalculo do posto ativo (fallback: primeiro posto)."""
        dados = self._dados
        if dados is None or not dados.calculos:
            return None
        posto = self._posto_atual()
        calculo = dados.calculos.get(posto) if posto is not None else None
        return calculo or next(iter(dados.calculos.values()), None)

    @property
    def available(self) -> bool:
        """Indisponível sem cálculo (degradação total de tarifa)."""
        return super().available and self._calculo_atual() is not None

    @property
    def native_value(self) -> float | None:
        """Valor do campo exposto, para o posto ativo."""
        calculo = self._calculo_atual()
        if calculo is None:
            return None
        return getattr(calculo, self._campo)


class TarifaFinalSensor(TarifaSensor):
    """Preço final com impostos e bandeira (R$/kWh) — painel de Energia."""

    _campo = "tarifa_final"
    _attr_icon = "mdi:cash-multiple"

    def __init__(
        self, coordinator: AneelTarifasCoordinator, entry: ConfigEntry
    ) -> None:
        """Inicializa o sensor principal."""
        super().__init__(coordinator, entry, "tarifa_final")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Atributos: fonte, posto ativo e tarifas por posto (Branca)."""
        dados = self._dados
        attrs = self._atributos_padrao(
            dados.fonte_tarifa if dados is not None else None
        )
        posto = self._posto_atual()
        if posto is not None:
            attrs[ATTR_POSTO_TARIFARIO] = posto
        if dados is not None and self._eh_branca() and dados.calculos:
            attrs[ATTR_TARIFA_POR_POSTO] = {
                nome_posto: round(calculo.tarifa_final, 5)
                for nome_posto, calculo in dados.calculos.items()
            }
        return attrs


class TarifaSemImpostosSensor(TarifaSensor):
    """TUSD + TE, antes de impostos e bandeira (R$/kWh)."""

    _campo = "tarifa_sem_impostos"
    _attr_icon = "mdi:cash"

    def __init__(
        self, coordinator: AneelTarifasCoordinator, entry: ConfigEntry
    ) -> None:
        """Inicializa o sensor."""
        super().__init__(coordinator, entry, "tarifa_sem_impostos")


class TUSDSensor(TarifaSensor):
    """Uso do sistema de distribuição (R$/kWh) do posto ativo."""

    _campo = "tarifa_tusd"
    _attr_icon = "mdi:transmission-tower"

    def __init__(
        self, coordinator: AneelTarifasCoordinator, entry: ConfigEntry
    ) -> None:
        """Inicializa o sensor."""
        super().__init__(coordinator, entry, "tarifa_tusd")


class TESensor(TarifaSensor):
    """Tarifa de energia (R$/kWh) do posto ativo."""

    _campo = "tarifa_te"
    _attr_icon = "mdi:flash"

    def __init__(
        self, coordinator: AneelTarifasCoordinator, entry: ConfigEntry
    ) -> None:
        """Inicializa o sensor."""
        super().__init__(coordinator, entry, "tarifa_te")


class AdicionalBandeiraSensor(TarifaSensor):
    """Adicional da bandeira tarifária vigente (R$/kWh)."""

    _campo = "adicional_bandeira"
    _attr_icon = "mdi:flag-variant-outline"

    def __init__(
        self, coordinator: AneelTarifasCoordinator, entry: ConfigEntry
    ) -> None:
        """Inicializa o sensor."""
        super().__init__(coordinator, entry, "adicional_bandeira")


class BandeiraAtualSensor(AneelBaseEntity, SensorEntity):
    """Bandeira tarifária vigente (Verde, Amarela, Vermelha P1/P2…)."""

    _attr_icon = "mdi:flag-variant"
    _attr_translation_key = "bandeira_atual"

    def __init__(
        self, coordinator: AneelTarifasCoordinator, entry: ConfigEntry
    ) -> None:
        """Inicializa o sensor."""
        super().__init__(coordinator, entry, "bandeira_atual")

    @property
    def available(self) -> bool:
        """Indisponível quando nenhuma bandeira foi obtida (degradação)."""
        dados = self._dados
        return (
            super().available
            and dados is not None
            and dados.bandeira is not None
        )

    @property
    def native_value(self) -> str | None:
        """Nome da bandeira acionada na competência vigente."""
        dados = self._dados
        return dados.bandeira.nome if dados is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Atributos da bandeira (adicional, competência e origem)."""
        dados = self._dados
        if dados is None or dados.bandeira is None:
            return {}
        attrs = self._atributos_padrao(dados.fonte_bandeira)
        attrs.update(
            {
                "bandeira": dados.bandeira.nome,
                "adicional_rsmwh": dados.bandeira.adicional_rsmwh,
                "adicional_rskwh": round(dados.bandeira.adicional, 5),
                "mes_anterior": dados.bandeira.mes_anterior,
                "consultado_em": (
                    dados.bandeira.consultado_em.isoformat()
                    if dados.bandeira.consultado_em is not None
                    else None
                ),
            }
        )
        return attrs


class PostoTarifarioSensor(AneelBaseEntity, SensorEntity):
    """Posto tarifário ativo (só criado na modalidade Branca)."""

    _attr_icon = "mdi:timetable"
    _attr_translation_key = "posto_tarifario"

    def __init__(
        self, coordinator: AneelTarifasCoordinator, entry: ConfigEntry
    ) -> None:
        """Inicializa o sensor e a verificação periódica do posto."""
        super().__init__(coordinator, entry, "posto_tarifario")
        self._cancelador: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        """Registra a verificação periódica do posto."""
        await super().async_added_to_hass()
        self._cancelador = async_track_time_interval(
            self.hass, self._ao_mudar_periodo, INTERVALO_POSTO
        )

    async def async_will_remove_from_hass(self) -> None:
        """Cancela a verificação periódica."""
        if self._cancelador is not None:
            self._cancelador()
            self._cancelador = None

    @callback
    def _ao_mudar_periodo(self, agora: datetime) -> None:
        """Reescreve o estado quando o posto ativo pode ter mudado."""
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Indisponível sem tarifa Branca carregada."""
        return super().available and self._eh_branca_dados()

    @property
    def native_value(self) -> str | None:
        """Posto ativo no momento (Ponta, Intermediário, Fora ponta)."""
        return self.coordinator.posto_ativo(dt_util.now())

    def _eh_branca_dados(self) -> bool:
        """Modalidade Branca com tarifa carregada."""
        dados = self._dados
        return (
            dados is not None
            and dados.tarifa is not None
            and dados.tarifa.modalidade == MODALIDADE_BRANCA
        )


class CustoFixoMensalSensor(AneelBaseEntity, SensorEntity):
    """CIP/COSIP configurada nas opções (R$/mês) — informativo.

    Custo fixo da fatura: não entra no R$/kWh (o painel de Energia usa
    apenas o preço unitário), mas serve de referência e para automações
    que estimam a fatura completa.
    """

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = UNIT_REAIS
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:receipt-text"
    _attr_translation_key = "custo_fixo_mensal"

    def __init__(
        self, coordinator: AneelTarifasCoordinator, entry: ConfigEntry
    ) -> None:
        """Inicializa o sensor."""
        super().__init__(coordinator, entry, "custo_fixo_mensal")

    @property
    def native_value(self) -> float:
        """Valor configurado de CIP/COSIP (R$/mês)."""
        opcoes = self._entry.options
        try:
            return float(opcoes.get(OPT_CIP_COSIP, DEFAULT_CIP_COSIP))
        except (TypeError, ValueError):
            return DEFAULT_CIP_COSIP


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Cria os sensores da entry (coordinator em entry.runtime_data)."""
    coordinator: AneelTarifasCoordinator = entry.runtime_data
    entidades: list[SensorEntity] = [
        TarifaFinalSensor(coordinator, entry),
        TarifaSemImpostosSensor(coordinator, entry),
        TUSDSensor(coordinator, entry),
        TESensor(coordinator, entry),
        AdicionalBandeiraSensor(coordinator, entry),
        BandeiraAtualSensor(coordinator, entry),
        CustoFixoMensalSensor(coordinator, entry),
    ]
    if entry.data.get(CONF_MODALIDADE) == MODALIDADE_BRANCA:
        entidades.append(PostoTarifarioSensor(coordinator, entry))
    async_add_entities(entidades)
