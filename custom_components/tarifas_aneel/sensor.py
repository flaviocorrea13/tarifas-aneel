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
from datetime import date, datetime, timedelta
import logging
from typing import Any, Final

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from custom_components.tarifas_aneel.ciclo import (
    LeituraCiclo,
    atualizar_leitura,
    calcular_custo_ciclo,
    delta_kwh,
    fim_ciclo,
    inicio_ciclo,
    normalizar_dia,
)
from custom_components.tarifas_aneel.const import (
    ATTR_CICLO_FIM,
    ATTR_CICLO_INICIO,
    ATTR_COMPENSACAO_CONSIDERADA,
    ATTR_CONSUMO_KWH,
    ATTR_CONSUMO_LIQUIDO_KWH,
    ATTR_CREDITOS_NAO_CONSIDERADOS,
    ATTR_DIA_LEITURA,
    ATTR_INJECAO_KWH,
    ATTR_POSTO_TARIFARIO,
    ATTR_RESET_DETECTADO,
    ATTR_TARIFA_POR_POSTO,
    CONF_MODALIDADE,
    DEFAULT_CIP_COSIP,
    MODALIDADE_BRANCA,
    OPT_CIP_COSIP,
    OPT_CONSUMO_ENTITY_ID,
    OPT_DIA_LEITURA,
    OPT_INJECAO_ENTITY_ID,
    STORE_KEY_CICLO,
    STORE_VERSION_CICLO,
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
# O ciclo de leitura vira à meia-noite; a verificação horária garante a
# rotação da baseline mesmo sem mudança nos sensores.
INTERVALO_CICLO: Final = timedelta(hours=1)
# Debounce da persistência do baseline (segundos).
ATRASO_SAVE_CICLO: Final = 5.0

_LOGGER: Final = logging.getLogger(__name__)


class TarifaSensor(AneelBaseEntity, SensorEntity):
    """Sensor numérico de tarifa (um campo de ResultadoCalculo, R$/kWh)."""

    _attr_native_unit_of_measurement = UNIT_PRECO_ENERGIA
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 5
    _campo: str = ""
    # Sensores de preço que dependem de impostos expõem os atributos de
    # configuração/revisão (final e sem impostos).
    _expoe_impostos: bool = False

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

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Atributos padrão e, se aplicável, os de impostos."""
        dados = self._dados
        attrs = self._atributos_padrao(
            dados.fonte_tarifa if dados is not None else None
        )
        if self._expoe_impostos:
            attrs.update(self._atributos_impostos())
        return attrs


class TarifaFinalSensor(TarifaSensor):
    """Preço final com impostos e bandeira (R$/kWh) — painel de Energia."""

    _campo = "tarifa_final"
    _expoe_impostos = True
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
        attrs = super().extra_state_attributes
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
    _expoe_impostos = True
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


class CustoEstimadoCicloSensor(AneelBaseEntity, SensorEntity):
    """Estimativa do custo do ciclo de leitura atual (R$).

    O ciclo começa no dia de leitura configurado (1 a 28; ausente = dia 1,
    ou seja, mês calendário). O consumo é a **variação** dos sensores
    totalizadores desde o início do ciclo, não o valor absoluto do
    medidor:

    ``consumo_liquido = max(delta_consumo - delta_injecao, 0)``
    ``custo = consumo_liquido x tarifa_final + CIP/COSIP``

    Um medidor que volta (reset/rollover) tem a baseline zerada. Créditos
    acumulados de ciclos anteriores (saldo de GD) não são considerados.
    """

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = UNIT_REAIS
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:calculator"
    _attr_translation_key = "custo_estimado_ciclo"

    def __init__(
        self, coordinator: AneelTarifasCoordinator, entry: ConfigEntry
    ) -> None:
        """Inicializa a estimativa, a baseline e o rastreio das origens."""
        super().__init__(coordinator, entry, "custo_estimado_ciclo")
        self._store: Store[dict[str, Any]] = Store(
            self.coordinator.hass,
            STORE_VERSION_CICLO,
            f"{STORE_KEY_CICLO}_{entry.entry_id}",
        )
        self._consumo: LeituraCiclo | None = None
        self._injecao: LeituraCiclo | None = None
        self._cancelar_estado: Callable[[], None] | None = None
        self._cancelar_relogio: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        """Carrega a baseline persistida e passa a acompanhar as origens."""
        await super().async_added_to_hass()
        await self._async_carregar_baseline()
        self._recalcular()
        ids = [
            str(valor)
            for valor in (
                self._entry.options.get(OPT_CONSUMO_ENTITY_ID),
                self._entry.options.get(OPT_INJECAO_ENTITY_ID),
            )
            if valor
        ]
        if ids:
            self._cancelar_estado = async_track_state_change_event(
                self.hass, ids, self._ao_mudar_origem
            )
        self._cancelar_relogio = async_track_time_interval(
            self.hass, self._ao_mudar_relogio, INTERVALO_CICLO
        )

    async def async_will_remove_from_hass(self) -> None:
        """Cancela o rastreio e grava a baseline final."""
        if self._cancelar_estado is not None:
            self._cancelar_estado()
            self._cancelar_estado = None
        if self._cancelar_relogio is not None:
            self._cancelar_relogio()
            self._cancelar_relogio = None
        await self._store.async_save(self._payload())

    @callback
    def _ao_mudar_origem(self, event: Any) -> None:
        """Reavalia a estimativa quando consumo/injeção mudam."""
        self._recalcular()
        self.async_write_ha_state()

    @callback
    def _ao_mudar_relogio(self, agora: datetime) -> None:
        """Reavalia a cada hora (rotação do ciclo e baseline)."""
        self._recalcular()
        self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Leitura dos medidores e baseline
    # ------------------------------------------------------------------
    def _valor_kwh(self, chave: str) -> float | None:
        """Lê o valor numérico (kWh) de uma entidade configurada."""
        entity_id = self._entry.options.get(chave)
        if not entity_id:
            return None
        estado = self.hass.states.get(str(entity_id))
        if estado is None or estado.state in ("unknown", "unavailable", ""):
            return None
        try:
            return float(estado.state)
        except (TypeError, ValueError):
            return None

    def _dia_leitura(self) -> int:
        """Dia de leitura normalizado (1..28; ausente = 1)."""
        return normalizar_dia(self._entry.options.get(OPT_DIA_LEITURA))

    def _ciclo_atual(self) -> date:
        """Início do ciclo de leitura que contém hoje."""
        return inicio_ciclo(dt_util.now().date(), self._dia_leitura())

    def _recalcular(
        self,
    ) -> tuple[date, LeituraCiclo | None, LeituraCiclo | None]:
        """Atualiza as leituras do ciclo e devolve o estado corrente."""
        inicio = self._ciclo_atual()
        consumo = self._valor_kwh(OPT_CONSUMO_ENTITY_ID)
        if consumo is not None:
            self._consumo = atualizar_leitura(self._consumo, consumo, inicio)
        injecao = self._valor_kwh(OPT_INJECAO_ENTITY_ID)
        if injecao is not None:
            self._injecao = atualizar_leitura(self._injecao, injecao, inicio)
        if self._consumo is not None or self._injecao is not None:
            self._agendar_save()
        return inicio, self._consumo, self._injecao

    def _payload(self) -> dict[str, Any]:
        """Conteúdo persistido (baseline por entidade e por ciclo)."""
        return {
            "consumo_entity": self._entry.options.get(OPT_CONSUMO_ENTITY_ID),
            "injecao_entity": self._entry.options.get(OPT_INJECAO_ENTITY_ID),
            "consumo": self._consumo.to_dict() if self._consumo else None,
            "injecao": self._injecao.to_dict() if self._injecao else None,
        }

    def _agendar_save(self) -> None:
        """Agenda a persistência da baseline (com debounce)."""
        self._store.async_delay_save(self._payload, ATRASO_SAVE_CICLO)

    async def _async_carregar_baseline(self) -> None:
        """Recompõe a baseline persistida; descarta se a entidade mudou."""
        dados = await self._store.async_load()
        if not isinstance(dados, dict):
            return
        if dados.get("consumo_entity") != self._entry.options.get(
            OPT_CONSUMO_ENTITY_ID
        ):
            _LOGGER.debug("Baseline do ciclo ignorada: sensor de consumo mudou")
            return
        try:
            self._consumo = (
                LeituraCiclo.from_dict(dados["consumo"])
                if dados.get("consumo")
                else None
            )
            if dados.get("injecao_entity") == self._entry.options.get(
                OPT_INJECAO_ENTITY_ID
            ):
                self._injecao = (
                    LeituraCiclo.from_dict(dados["injecao"])
                    if dados.get("injecao")
                    else None
                )
        except (KeyError, TypeError, ValueError) as err:
            _LOGGER.warning(
                "Baseline do ciclo corrompida, será reconstruída: %s", err
            )
            self._consumo = None
            self._injecao = None

    # ------------------------------------------------------------------
    # Cálculo exposto
    # ------------------------------------------------------------------
    def _calculo_atual(self) -> ResultadoCalculo | None:
        """Cálculo do posto ativo (fallback: primeiro posto)."""
        dados = self._dados
        if dados is None or not dados.calculos:
            return None
        posto = self.coordinator.posto_ativo(dt_util.now())
        if posto is None:
            return next(iter(dados.calculos.values()), None)
        return dados.calculos.get(posto) or next(
            iter(dados.calculos.values()), None
        )

    def _cip_cosip(self) -> float:
        """CIP/COSIP configurada (R$/mês)."""
        try:
            return float(
                self._entry.options.get(OPT_CIP_COSIP, DEFAULT_CIP_COSIP)
            )
        except (TypeError, ValueError):
            return DEFAULT_CIP_COSIP

    @property
    def available(self) -> bool:
        """Disponível apenas com o sensor de consumo e a tarifa carregados."""
        return (
            super().available
            and self._valor_kwh(OPT_CONSUMO_ENTITY_ID) is not None
            and self._calculo_atual() is not None
        )

    @property
    def last_reset(self) -> datetime | None:
        """Início do ciclo atual (interpretação de ``state_class: total``)."""
        if self._consumo is None:
            return None
        return dt_util.start_of_local_day(self._consumo.inicio)

    @property
    def native_value(self) -> float | None:
        """Custo estimado do ciclo (R$), com consumo líquido."""
        inicio, consumo, injecao = self._recalcular()
        calculo = self._calculo_atual()
        if consumo is None or calculo is None:
            return None
        return calcular_custo_ciclo(
            delta_kwh(consumo, inicio),
            delta_kwh(injecao, inicio),
            calculo.tarifa_final,
            self._cip_cosip(),
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Memória de cálculo e período do ciclo estimado."""
        dados = self._dados
        attrs = self._atributos_padrao(
            dados.fonte_tarifa if dados is not None else None
        )
        inicio, consumo, injecao = self._recalcular()
        calculo = self._calculo_atual()
        consumo_kwh = delta_kwh(consumo, inicio)
        injecao_kwh = delta_kwh(injecao, inicio)
        dia = self._dia_leitura()
        attrs.update(
            {
                ATTR_DIA_LEITURA: dia,
                ATTR_CICLO_INICIO: inicio.isoformat(),
                ATTR_CICLO_FIM: fim_ciclo(inicio, dia).isoformat(),
                ATTR_CONSUMO_KWH: round(consumo_kwh, 3),
                ATTR_INJECAO_KWH: round(injecao_kwh, 3),
                ATTR_CONSUMO_LIQUIDO_KWH: round(
                    max(consumo_kwh - injecao_kwh, 0.0), 3
                ),
                "tarifa_final": (
                    round(calculo.tarifa_final, 5) if calculo else None
                ),
                "cip_cosip": self._cip_cosip(),
                ATTR_RESET_DETECTADO: bool(
                    (consumo is not None and consumo.reset)
                    or (injecao is not None and injecao.reset)
                ),
                ATTR_COMPENSACAO_CONSIDERADA: self._injecao is not None,
                ATTR_CREDITOS_NAO_CONSIDERADOS: True,
                "entidade_consumo": self._entry.options.get(
                    OPT_CONSUMO_ENTITY_ID
                ),
                "entidade_injecao": self._entry.options.get(
                    OPT_INJECAO_ENTITY_ID
                ),
            }
        )
        return attrs


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
    if entry.options.get(OPT_CONSUMO_ENTITY_ID):
        entidades.append(CustoEstimadoCicloSensor(coordinator, entry))
    async_add_entities(entidades)
