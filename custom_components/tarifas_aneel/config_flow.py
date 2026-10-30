"""Config flow e options flow da integração Tarifas ANEEL.

Fluxo de configuração: o usuário escolhe o recorte tarifário —
distribuidora, subgrupo, classe, subclasse, modalidade e detalhe — entre os
valores reais levantados na Fase 0. Antes de criar a entry, o recorte é
validado na fonte (camada 1 JSON, depois camada 2 CSV) para garantir que
existem tarifas publicadas, evitando entries sem dado.

``unique_id`` = ``distribuidora_subgrupo_modalidade``, com o detalhe
acrescentado quando não é o padrão ("Não se aplica") — assim o mesmo
recorte não gera entries duplicadas, mas uma variante SCEE continua
possível.

Fluxo de opções: alíquotas de ICMS/PIS/COFINS em % (padrão 0 — o usuário
deve conferir os valores reais na própria fatura), escolha da base do
PIS/COFINS (sem ICMS por padrão), CIP/COSIP em R$/mês, intervalo de
atualização em horas (mínimo 6), entidades de consumo e injeção (kWh)
opcionais e, apenas na modalidade Branca, a janela de ponta.

Cada gravação do options flow registra a data da revisão das alíquotas em
``aliquotas_revisadas_em``; o coordinator usa essa data no lembrete de
revisão de impostos.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util
import voluptuous as vol

from custom_components.tarifas_aneel.api import (
    AneelApiError,
    TarifaFiltro,
    async_fetch_tarifa_csv,
    async_fetch_tarifa_json,
)
from custom_components.tarifas_aneel.const import (
    CLASSES,
    CONF_CLASSE,
    CONF_DETALHE,
    CONF_DISTRIBUIDORA,
    CONF_MODALIDADE,
    CONF_SUBCLASSE,
    CONF_SUBGRUPO,
    DEFAULT_CIP_COSIP,
    DEFAULT_CLASSE,
    DEFAULT_COFINS,
    DEFAULT_DETALHE,
    DEFAULT_ICMS,
    DEFAULT_PIS,
    DEFAULT_PIS_COFINS_SEM_ICMS,
    DEFAULT_PONTA_FIM,
    DEFAULT_PONTA_INICIO,
    DEFAULT_SUBCLASSE,
    DEFAULT_SUBGRUPO,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DETALHE_SCEE,
    DISTRIBUTOR_NAMES,
    DISTRIBUTORS,
    DOMAIN,
    MIN_UPDATE_INTERVAL_HOURS,
    MODALIDADE_BRANCA,
    MODALIDADE_CONVENCIONAL,
    MODALIDADES_GRUPO_B,
    NAO_SE_APLICA,
    OPT_ALIQUOTAS_REVISADAS_EM,
    OPT_CIP_COSIP,
    OPT_COFINS,
    OPT_CONSUMO_ENTITY_ID,
    OPT_ICMS,
    OPT_INJECAO_ENTITY_ID,
    OPT_PIS,
    OPT_PIS_COFINS_SEM_ICMS,
    OPT_PONTA_FIM,
    OPT_PONTA_INICIO,
    OPT_UPDATE_INTERVAL,
    SUBCLASSES,
    SUBGRUPOS,
)
from custom_components.tarifas_aneel.models import TarifaData

_LOGGER: Final = logging.getLogger(__name__)

# Detalhe: "Não se aplica" (padrão) ou "SCEE" (TE reduzida p/ GD — Fase 0).
DETALHES: Final[tuple[str, ...]] = (NAO_SE_APLICA, DETALHE_SCEE)

# Limites dos campos numéricos do options flow.
MAX_ALIQUOTA_PCT: Final = 100.0
MAX_CIP_COSIP: Final = 1000.0  # R$/mês (valores reais ficam bem abaixo)
# 720 h = 30 dias; acima disso o usuário deve desabilitar a entry.
MAX_UPDATE_INTERVAL_HOURS: Final = 720


def _opcoes_distribuidora() -> list[dict[str, str]]:
    """Dropdown de distribuidoras com desambiguação de rótulos repetidos.

    O dataset tem grafias distintas para a mesma empresa (ex.: as duas
    "CPFL Santa Cruz", com CNPJs diferentes). Quando o rótulo amigável
    coincide para siglas diferentes, a sigla exata entra entre colchetes
    para que as duas opções sejam distinguíveis.
    """
    contagem: dict[str, int] = {}
    rotulos: list[str] = []
    for sigla in DISTRIBUTORS:
        rotulo = DISTRIBUTOR_NAMES.get(sigla, sigla)
        rotulos.append(rotulo)
        contagem[rotulo] = contagem.get(rotulo, 0) + 1
    return [
        {
            "value": sigla,
            "label": f"{rotulo} [{sigla}]" if contagem[rotulo] > 1 else rotulo,
        }
        for sigla, rotulo in zip(DISTRIBUTORS, rotulos, strict=True)
    ]


def _seletor_lista(valores: tuple[str, ...]) -> selector.SelectSelector:
    """Seletor dropdown simples para uma tupla de valores."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=list(valores),
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _seletor_numero(
    unidade: str,
    minimo: float,
    maximo: float,
    passo: float,
) -> selector.NumberSelector:
    """Seletor numérico em caixa de texto com unidade."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimo,
            max=maximo,
            step=passo,
            unit_of_measurement=unidade,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _validar_percentuais(
    icms_pct: float,
    pis_pct: float,
    cofins_pct: float,
    pis_cofins_sem_icms: bool,
) -> str | None:
    """Valida os percentuais e devolve a chave de erro (ou ``None``).

    As regras espelham :func:`calc.validar_aliquotas`:

    * ``0 <= ICMS < 100``;
    * ``PIS`` e ``COFINS`` não negativos;
    * ``0 <= PIS + COFINS < 100``;
    * na fórmula antiga, ``ICMS + PIS + COFINS < 100``.
    """
    if icms_pct < 0 or icms_pct >= 100:
        return "icms_invalido"
    if pis_pct < 0 or cofins_pct < 0:
        return "aliquota_negativa"
    if pis_pct + cofins_pct >= 100:
        return "pis_cofins_invalidos"
    if not pis_cofins_sem_icms and icms_pct + pis_pct + cofins_pct >= 100:
        return "soma_aliquotas"
    return None


ESQUEMA_CONFIG: Final = vol.Schema(
    {
        vol.Required(CONF_DISTRIBUIDORA): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=_opcoes_distribuidora(),
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Required(CONF_SUBGRUPO, default=DEFAULT_SUBGRUPO): _seletor_lista(
            SUBGRUPOS
        ),
        vol.Required(CONF_CLASSE, default=DEFAULT_CLASSE): _seletor_lista(
            CLASSES
        ),
        vol.Required(
            CONF_SUBCLASSE, default=DEFAULT_SUBCLASSE
        ): _seletor_lista(SUBCLASSES),
        vol.Required(
            CONF_MODALIDADE, default=MODALIDADE_CONVENCIONAL
        ): _seletor_lista(MODALIDADES_GRUPO_B),
        vol.Required(CONF_DETALHE, default=DEFAULT_DETALHE): _seletor_lista(
            DETALHES
        ),
    }
)


def _unique_id_da_filtro(filtro: TarifaFiltro) -> str:
    """Unique_id estável do recorte (distribuidora+subgrupo+modalidade).

    O detalhe entra no unique_id apenas quando difere do padrão ("Não se
    aplica"), permitindo uma entry normal e uma variante SCEE do mesmo
    recorte sem colisão.
    """
    partes = [filtro.distribuidora, filtro.subgrupo, filtro.modalidade]
    if filtro.detalhe != DEFAULT_DETALHE:
        partes.append(filtro.detalhe)
    return "_".join(partes)


def _titulo_da_filtro(filtro: TarifaFiltro) -> str:
    """Título amigável da entry (nome da distribuidora + recorte)."""
    nome = DISTRIBUTOR_NAMES.get(filtro.distribuidora, filtro.distribuidora)
    titulo = f"Tarifas {nome} — {filtro.subgrupo} • {filtro.modalidade}"
    if filtro.detalhe != DEFAULT_DETALHE:
        titulo = f"{titulo} • {filtro.detalhe}"
    return titulo


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Fluxo de configuração da integração Tarifas ANEEL."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Passo principal: escolha do recorte + validação na ANEEL."""
        errors: dict[str, str] = {}
        if user_input is not None:
            filtro = TarifaFiltro(
                distribuidora=user_input[CONF_DISTRIBUIDORA],
                subgrupo=user_input[CONF_SUBGRUPO],
                modalidade=user_input[CONF_MODALIDADE],
                classe=user_input[CONF_CLASSE],
                subclasse=user_input[CONF_SUBCLASSE],
                detalhe=user_input[CONF_DETALHE],
            )
            await self.async_set_unique_id(_unique_id_da_filtro(filtro))
            self._abort_if_unique_id_mismatch()
            if (erro := await self._async_validar(filtro)) is None:
                return self.async_create_entry(
                    title=_titulo_da_filtro(filtro), data=user_input
                )
            errors["base"] = erro
        return self.async_show_form(
            step_id="user", data_schema=ESQUEMA_CONFIG, errors=errors
        )

    async def _async_validar(self, filtro: TarifaFiltro) -> str | None:
        """Confirma na fonte que o recorte tem tarifas publicadas.

        Consulta a camada 1 (JSON) e, em caso de falha ou lista vazia, a
        camada 2 (CSV). Devolve ``None`` quando o recorte é válido, ou a
        chave de erro a exibir no formulário.
        """
        tarifas: list[TarifaData] = []
        try:
            tarifas = await async_fetch_tarifa_json(self.hass, filtro)
        except AneelApiError as err:
            _LOGGER.debug("Validação: camada 1 (JSON) falhou: %s", err)
        if not tarifas:
            try:
                tarifas = await async_fetch_tarifa_csv(self.hass, filtro)
            except AneelApiError as err:
                _LOGGER.debug("Validação: camada 2 (CSV) falhou: %s", err)
                return "cannot_connect"
        if not tarifas:
            _LOGGER.debug(
                "Validação: nenhum registro para %s (%s/%s, detalhe %s)",
                filtro.distribuidora,
                filtro.subgrupo,
                filtro.modalidade,
                filtro.detalhe,
            )
            return "sem_dados"
        _LOGGER.debug(
            "Validação OK: %d vigência(s) encontrada(s) para o recorte",
            len(tarifas),
        )
        return None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlowTarifas:
        """Cria o options flow da entry."""
        return OptionsFlowTarifas(config_entry)


class OptionsFlowTarifas(config_entries.OptionsFlow):
    """Options flow: impostos, CIP/COSIP, intervalo, consumo e ponta."""

    def __init__(self, entry: ConfigEntry) -> None:
        """Guarda a entry em atributo próprio.

        ``self.config_entry`` passa a ser gerenciado pelo Home Assistant a
        partir do 2025.3 e a atribuição explícita deixa de funcionar no
        2025.12; guardar em ``self._entry`` (nome próprio) funciona em
        todas as versões suportadas (>= 2024.10) sem deprecação.
        """
        self._entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Passo único de opções."""
        errors: dict[str, str] = {}
        if user_input is not None:
            sem_icms = bool(
                user_input.get(
                    OPT_PIS_COFINS_SEM_ICMS, DEFAULT_PIS_COFINS_SEM_ICMS
                )
            )
            erro = _validar_percentuais(
                float(user_input[OPT_ICMS]),
                float(user_input[OPT_PIS]),
                float(user_input[OPT_COFINS]),
                sem_icms,
            )
            if erro is not None:
                errors["base"] = erro
            else:
                dados = dict(user_input)
                dados[OPT_ALIQUOTAS_REVISADAS_EM] = self._carimbo_revisao()
                _LOGGER.debug(
                    "Opções atualizadas para a entry %s (revisão de "
                    "impostos: %s)",
                    self._entry.entry_id,
                    dados[OPT_ALIQUOTAS_REVISADAS_EM],
                )
                return self.async_create_entry(title="", data=dados)
        return self.async_show_form(
            step_id="init", data_schema=self._esquema(), errors=errors
        )

    @staticmethod
    def _carimbo_revisao() -> str:
        """Data (ISO) em que as alíquotas foram salvas.

        Toda gravação do options flow registra a data: salvar as opções é
        a forma de o usuário confirmar que conferiu a conta de luz e
        encerrar o lembrete de revisão.
        """
        return dt_util.now().date().isoformat()

    def _esquema(self) -> vol.Schema:
        """Esquema com os valores atuais como padrão.

        A janela de ponta só aparece na modalidade Branca (não se aplica à
        Convencional; o coordinator a ignora nesses casos).
        """
        opcoes = self._entry.options
        campos: dict[Any, Any] = {
            vol.Required(
                OPT_ICMS, default=float(opcoes.get(OPT_ICMS, DEFAULT_ICMS))
            ): _seletor_numero("%", 0.0, MAX_ALIQUOTA_PCT, 0.01),
            vol.Required(
                OPT_PIS, default=float(opcoes.get(OPT_PIS, DEFAULT_PIS))
            ): _seletor_numero("%", 0.0, MAX_ALIQUOTA_PCT, 0.01),
            vol.Required(
                OPT_COFINS,
                default=float(opcoes.get(OPT_COFINS, DEFAULT_COFINS)),
            ): _seletor_numero("%", 0.0, MAX_ALIQUOTA_PCT, 0.01),
            vol.Required(
                OPT_PIS_COFINS_SEM_ICMS,
                default=bool(
                    opcoes.get(
                        OPT_PIS_COFINS_SEM_ICMS,
                        DEFAULT_PIS_COFINS_SEM_ICMS,
                    )
                ),
            ): selector.BooleanSelector(),
            vol.Required(
                OPT_CIP_COSIP,
                default=float(opcoes.get(OPT_CIP_COSIP, DEFAULT_CIP_COSIP)),
            ): _seletor_numero("R$/mês", 0.0, MAX_CIP_COSIP, 0.01),
            vol.Required(
                OPT_UPDATE_INTERVAL,
                default=int(
                    opcoes.get(OPT_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_HOURS)
                ),
            ): _seletor_numero(
                "h",
                float(MIN_UPDATE_INTERVAL_HOURS),
                float(MAX_UPDATE_INTERVAL_HOURS),
                1.0,
            ),
            vol.Optional(
                OPT_CONSUMO_ENTITY_ID,
                description={
                    "suggested_value": opcoes.get(OPT_CONSUMO_ENTITY_ID)
                },
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(
                OPT_INJECAO_ENTITY_ID,
                description={
                    "suggested_value": opcoes.get(OPT_INJECAO_ENTITY_ID)
                },
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
        }
        if self._entry.data.get(CONF_MODALIDADE) == MODALIDADE_BRANCA:
            campos[
                vol.Required(
                    OPT_PONTA_INICIO,
                    default=str(
                        opcoes.get(OPT_PONTA_INICIO, DEFAULT_PONTA_INICIO)
                    ),
                )
            ] = selector.TimeSelector()
            campos[
                vol.Required(
                    OPT_PONTA_FIM,
                    default=str(opcoes.get(OPT_PONTA_FIM, DEFAULT_PONTA_FIM)),
                )
            ] = selector.TimeSelector()
        return vol.Schema(campos)
