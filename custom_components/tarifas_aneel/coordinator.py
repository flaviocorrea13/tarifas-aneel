"""Coordinator da integração Tarifas ANEEL.

Estratégia de atualização (a cada 12 h por padrão, mínimo 6 h):

* **Tarifa e bandeira são resolvidos de forma independente**, cada um
  percorrendo o fallback em 3 camadas (``fonte_dado`` é registrado
  separadamente):
  1. **Camada 1 — API JSON oficial** (``datastore_search``);
  2. **Camada 2 — CSV de dados abertos** (``datastore/dump``);
  3. **Camada 3 — cache persistente** com :class:`Store` (sobrevive a
     reinícios).

* **Bandeira**: tenta o mês corrente; sem registro, tenta o mês anterior
  (``relativedelta``). Isso acontece em cada camada, antes de cair no cache.

* **Tarifa**: usa o registro cuja vigência já começou e ainda não terminou
  (``DatInicioVigencia <= hoje <= DatFimVigencia``); se nenhum estiver
  vigente, usa o mais recente — a tarifa vale por data de vigência, não é
  mensal.

* ``UpdateFailed`` só é lançado quando as 3 camadas falham e não há cache
  nenhum. Falha parcial (ex.: tarifa da API + bandeira do cache) é sucesso.

* ``Repair issue`` é aberto quando o dado corrente vem só do cache há mais
  de 7 dias (última atualização real antiga) e fechado quando os dados
  reais voltam.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
import logging
from typing import Any, Final

from dateutil.relativedelta import relativedelta
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from custom_components.tarifas_aneel.api import (
    AneelApiError,
    TarifaFiltro,
    async_fetch_bandeira_csv,
    async_fetch_bandeira_json,
    async_fetch_tarifa_csv,
    async_fetch_tarifa_json,
)
from custom_components.tarifas_aneel.calc import calcular_tarifa, validar_aliquotas
from custom_components.tarifas_aneel.const import (
    DEFAULT_COFINS,
    DEFAULT_ICMS,
    DEFAULT_PIS,
    DEFAULT_PONTA_FIM,
    DEFAULT_PONTA_INICIO,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
    MIN_UPDATE_INTERVAL_HOURS,
    MODALIDADE_BRANCA,
    OPT_COFINS,
    OPT_ICMS,
    OPT_PIS,
    OPT_PONTA_FIM,
    OPT_PONTA_INICIO,
    OPT_UPDATE_INTERVAL,
    POSTO_FORA_PONTA,
    POSTO_INTERMEDIARIO,
    POSTO_PONTA,
    REPAIR_CACHE_MAX_AGE_DAYS,
    STORE_KEY,
    STORE_VERSION,
)
from custom_components.tarifas_aneel.models import (
    BandeiraData,
    FonteDado,
    ResultadoCalculo,
    TarifaData,
)

_LOGGER: Final = logging.getLogger(__name__)

REPAIR_ISSUE_CACHE: Final = "cache_antigo"

MINUTOS_EM_UMA_HORA: Final = 60
MINUTOS_EM_UM_DIA: Final = 1440


@dataclass
class DadosAneel:
    """Dados publicados pelo coordinator para as entidades."""

    filtro: TarifaFiltro
    tarifa: TarifaData | None = None
    bandeira: BandeiraData | None = None
    fonte_tarifa: FonteDado | None = None
    fonte_bandeira: FonteDado | None = None
    # Última vez em que dados REAIS (API ou CSV) chegaram — pode ser de um
    # ciclo anterior (sobrevive a reinícios via cache).
    ultima_atualizacao_real: datetime | None = None
    # ResultadoCalculo por posto ("Não se aplica" na Convencional).
    calculos: dict[str, ResultadoCalculo] = field(default_factory=dict)


@dataclass
class _CacheDados:
    """Conteúdo validado do cache persistente."""

    tarifa: TarifaData | None = None
    bandeira: BandeiraData | None = None
    ultima_atualizacao_real: datetime | None = None


def _posto_para_hora(hora: time, ponta_inicio: time, ponta_fim: time) -> str:
    """Determina o posto tarifário ativo para um horário (modalidade Branca).

    Janela de ponta definida pela distribuidora (configurável nas opções).
    Intermediário: 1 hora imediatamente antes e 1 hora imediatamente depois
    da ponta; demais horários são fora de ponta.
    """
    def minutos(valor: time) -> int:
        return valor.hour * 60 + valor.minute

    ini = minutos(ponta_inicio)
    fim = minutos(ponta_fim)
    atual = minutos(hora)
    antes = max(ini - MINUTOS_EM_UMA_HORA, 0)
    depois = min(fim + MINUTOS_EM_UMA_HORA, MINUTOS_EM_UM_DIA)
    # Janela que cruza a meia-noite (ex.: ponta 22:00-01:00) precisa de
    # comparação em dois intervalos.
    na_ponta = (
        (ini <= atual < fim) if ini <= fim else (atual >= ini or atual < fim)
    )
    no_intermediario = (antes <= atual < ini) or (fim <= atual < depois)
    if na_ponta:
        return POSTO_PONTA
    if no_intermediario:
        return POSTO_INTERMEDIARIO
    return POSTO_FORA_PONTA


def _pct_para_fracao(valor: Any) -> float:
    """Converte um percentual digitado (18) em fração (0.18)."""
    try:
        return float(valor) / 100.0
    except (TypeError, ValueError):
        return 0.0


class AneelTarifasCoordinator(DataUpdateCoordinator[DadosAneel]):
    """Coordena tarifas e bandeira com fallback JSON -> CSV -> cache."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        filtro: TarifaFiltro,
    ) -> None:
        """Inicializa o coordinator com intervalo das opções (mín. 6 h)."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"Tarifas ANEEL {filtro.distribuidora}",
            update_interval=timedelta(
                hours=self._intervalo_horas(entry.options)
            ),
        )
        self._filtro = filtro
        self._entry = entry
        self._store: Store[dict[str, Any]] = Store(
            hass, STORE_VERSION, f"{STORE_KEY}_{entry.entry_id}"
        )

    # ------------------------------------------------------------------
    # Configuração
    # ------------------------------------------------------------------
    @staticmethod
    def _intervalo_horas(opcoes: Any) -> int:
        try:
            horas = int(opcoes.get(OPT_UPDATE_INTERVAL))
        except (AttributeError, TypeError, ValueError):
            horas = DEFAULT_UPDATE_INTERVAL_HOURS
        return max(MIN_UPDATE_INTERVAL_HOURS, horas)

    def _aliquotas(self) -> tuple[float, float, float]:
        """Lê ICMS/PIS/COFINS das opções e converte para fração."""
        opcoes = self._entry.options
        return (
            _pct_para_fracao(opcoes.get(OPT_ICMS, DEFAULT_ICMS)),
            _pct_para_fracao(opcoes.get(OPT_PIS, DEFAULT_PIS)),
            _pct_para_fracao(opcoes.get(OPT_COFINS, DEFAULT_COFINS)),
        )

    def _janela_ponta(self) -> tuple[time, time]:
        """Lê a janela de ponta (modalidade Branca) das opções."""
        opcoes = self._entry.options

        def _hora(texto: Any, padrao: str) -> time:
            try:
                return time.fromisoformat(str(texto))
            except (TypeError, ValueError):
                return time.fromisoformat(padrao)

        inicio_bruto = str(opcoes.get(OPT_PONTA_INICIO, DEFAULT_PONTA_INICIO))
        fim_bruto = str(opcoes.get(OPT_PONTA_FIM, DEFAULT_PONTA_FIM))
        return (
            _hora(inicio_bruto, DEFAULT_PONTA_INICIO),
            _hora(fim_bruto, DEFAULT_PONTA_FIM),
        )

    # ------------------------------------------------------------------
    # API pública para entidades
    # ------------------------------------------------------------------
    def posto_ativo(self, agora: datetime) -> str | None:
        """Posto tarifário ativo em ``agora`` (só para modalidade Branca)."""
        dados = self.data
        if dados is None or dados.tarifa is None:
            return None
        if dados.tarifa.modalidade != MODALIDADE_BRANCA:
            return None
        ponta_inicio, ponta_fim = self._janela_ponta()
        return _posto_para_hora(
            agora.time(), ponta_inicio, ponta_fim
        )

    def calculo_por_posto(self, posto: str | None) -> ResultadoCalculo | None:
        """Resultado de cálculo para um posto (Convencional: único posto)."""
        dados = self.data
        if dados is None:
            return None
        if posto is None and dados.tarifa is not None:
            posto = next(iter(dados.tarifa.postos), None)
        return dados.calculos.get(posto) if posto is not None else None

    # ------------------------------------------------------------------
    # Ciclo de atualização
    # ------------------------------------------------------------------
    async def _async_update_data(self) -> DadosAneel:
        """Busca tarifa e bandeira com fallback independente por item."""
        agora = dt_util.utcnow()
        cache = await self._async_carregar_cache()

        tarifa, fonte_tarifa = await self._async_obter_tarifa(cache)
        bandeira, fonte_bandeira = await self._async_obter_bandeira(cache)

        if tarifa is None and bandeira is None:
            msg = (
                "Falha nas 3 camadas (JSON, CSV e cache) sem dado em cache "
                f"para {self._filtro.distribuidora}"
            )
            raise UpdateFailed(msg)
        if tarifa is None:
            _LOGGER.warning(
                "Tarifa indisponível para %s — entidades de tarifa ficarão "
                "sem valor até a próxima atualização (degradação)",
                self._filtro.distribuidora,
            )
        if bandeira is None:
            _LOGGER.warning(
                "Bandeira indisponível para %s — cálculo seguirá sem "
                "adicional de bandeira (degradação)",
                self._filtro.distribuidora,
            )

        teve_dado_real = fonte_tarifa in (FonteDado.API, FonteDado.CSV) or (
            fonte_bandeira in (FonteDado.API, FonteDado.CSV)
        )
        ultima_real = (
            agora
            if teve_dado_real
            else (cache.ultima_atualizacao_real if cache else None)
        )

        dados = DadosAneel(
            filtro=self._filtro,
            tarifa=tarifa,
            bandeira=bandeira,
            fonte_tarifa=fonte_tarifa,
            fonte_bandeira=fonte_bandeira,
            ultima_atualizacao_real=ultima_real,
            calculos=self._calcular_postos(tarifa, bandeira),
        )
        await self._async_gerenciar_repair(dados, agora)
        if teve_dado_real:
            await self._async_salvar_cache(dados)
        return dados

    # ------------------------------------------------------------------
    # Tarifa (3 camadas)
    # ------------------------------------------------------------------
    async def _async_obter_tarifa(
        self, cache: _CacheDados | None
    ) -> tuple[TarifaData | None, FonteDado | None]:
        """Tenta JSON, depois CSV, depois cache; independente da bandeira."""
        hoje = dt_util.now().date()

        # Camada 1 — JSON oficial
        try:
            candidatos = await async_fetch_tarifa_json(self.hass, self._filtro)
        except AneelApiError as err:
            _LOGGER.debug(
                "Camada 1 (JSON) falhou para tarifa: %s — tentando camada 2 (CSV)",
                err,
            )
            candidatos = []
        tarifa = self._selecionar_tarifa_vigente(candidatos, hoje)
        if tarifa is not None:
            _LOGGER.debug(
                "Tarifa obtida na camada 1 (JSON): vigência %s a %s",
                tarifa.inicio_vigencia,
                tarifa.fim_vigencia,
            )
            return tarifa, FonteDado.API

        # Camada 2 — CSV de dados abertos
        try:
            candidatos = await async_fetch_tarifa_csv(self.hass, self._filtro)
        except AneelApiError as err:
            _LOGGER.debug(
                "Camada 2 (CSV) falhou para tarifa: %s — tentando camada 3 (cache)",
                err,
            )
            candidatos = []
        tarifa = self._selecionar_tarifa_vigente(candidatos, hoje)
        if tarifa is not None:
            _LOGGER.debug(
                "Tarifa obtida na camada 2 (CSV): vigência %s a %s",
                tarifa.inicio_vigencia,
                tarifa.fim_vigencia,
            )
            return tarifa, FonteDado.CSV

        # Camada 3 — cache persistente
        if cache is not None and cache.tarifa is not None:
            _LOGGER.debug(
                "Camada 3 (cache): tarifa do cache (última atualização real: %s)",
                cache.ultima_atualizacao_real,
            )
            return cache.tarifa, FonteDado.CACHE
        _LOGGER.debug("Tarifa: todas as camadas falharam (sem cache)")
        return None, None

    @staticmethod
    def _selecionar_tarifa_vigente(
        candidatos: list[TarifaData], hoje: date
    ) -> TarifaData | None:
        """Escolhe a tarifa vigente (início <= hoje <= fim) ou a mais recente.

        A tarifa vale por data de vigência/reajuste (não é mensal).
        ``candidatos`` já vem ordenado por início decrescente.
        """
        vigentes = [
            tarifa
            for tarifa in candidatos
            if tarifa.inicio_vigencia <= hoje
            and (tarifa.fim_vigencia is None or tarifa.fim_vigencia >= hoje)
        ]
        if vigentes:
            return vigentes[0]
        return candidatos[0] if candidatos else None

    # ------------------------------------------------------------------
    # Bandeira (3 camadas, com fallback de mês)
    # ------------------------------------------------------------------
    async def _async_obter_bandeira(
        self, cache: _CacheDados | None
    ) -> tuple[BandeiraData | None, FonteDado | None]:
        """Tenta JSON e CSV (mês atual -> mês anterior), depois cache."""
        hoje = dt_util.now().date()
        mes_atual = date(hoje.year, hoje.month, 1)
        mes_anterior = mes_atual - relativedelta(months=1)

        for fetch, fonte in (
            (async_fetch_bandeira_json, FonteDado.API),
            (async_fetch_bandeira_csv, FonteDado.CSV),
        ):
            bandeira = await self._async_bandeira_no_mes(
                fetch, mes_atual, mes_anterior
            )
            if bandeira is not None:
                _LOGGER.debug(
                    "Bandeira obtida na camada %s: %s (competência %s, "
                    "mês anterior: %s)",
                    fonte,
                    bandeira.nome,
                    bandeira.competencia,
                    bandeira.mes_anterior,
                )
                return bandeira, fonte

        if cache is not None and cache.bandeira is not None:
            _LOGGER.debug(
                "Camada 3 (cache): bandeira do cache (competência %s)",
                cache.bandeira.competencia,
            )
            return cache.bandeira, FonteDado.CACHE
        _LOGGER.debug("Bandeira: todas as camadas falharam (sem cache)")
        return None, None

    async def _async_bandeira_no_mes(
        self,
        fetch: Callable[[HomeAssistant, date], Awaitable[BandeiraData | None]],
        mes_atual: date,
        mes_anterior: date,
    ) -> BandeiraData | None:
        """Tenta o mês corrente; sem registro, usa o mês anterior."""
        try:
            bandeira = await fetch(self.hass, mes_atual)
        except AneelApiError as err:
            _LOGGER.debug(
                "Camada falhou para bandeira de %s: %s", mes_atual, err
            )
            bandeira = None
        if bandeira is None:
            _LOGGER.debug(
                "Bandeira de %s indisponível nesta camada — tentando o mês "
                "anterior (%s)",
                mes_atual,
                mes_anterior,
            )
            try:
                bandeira = await fetch(self.hass, mes_anterior)
            except AneelApiError as err:
                _LOGGER.debug(
                    "Camada falhou para bandeira de %s: %s", mes_anterior, err
                )
                bandeira = None
        if bandeira is not None and bandeira.competencia != mes_atual:
            bandeira = replace(bandeira, mes_anterior=True)
        return bandeira

    # ------------------------------------------------------------------
    # Cálculo (delegado a calc.py — nada de lógica aqui)
    # ------------------------------------------------------------------
    def _calcular_postos(
        self,
        tarifa: TarifaData | None,
        bandeira: BandeiraData | None,
    ) -> dict[str, ResultadoCalculo]:
        """Calcula o resultado por posto com as alíquotas das opções."""
        if tarifa is None:
            return {}
        icms, pis, cofins = self._aliquotas()
        adicional = bandeira.adicional if bandeira is not None else 0.0
        try:
            validar_aliquotas(icms, pis, cofins)
        except ValueError as err:
            _LOGGER.warning(
                "Alíquotas inválidas (%s) — calculando sem impostos "
                "(degradação)",
                err,
            )
            icms = pis = cofins = 0.0
        calculos: dict[str, ResultadoCalculo] = {}
        for posto, valores in tarifa.postos.items():
            try:
                calculos[posto] = calcular_tarifa(
                    valores.tusd,
                    valores.te,
                    adicional,
                    icms,
                    pis,
                    cofins,
                )
            except ValueError as err:
                # Valores de posto negativos/corrompidos: não podem derrubar
                # o ciclo todo — descarta só este posto.
                _LOGGER.warning(
                    "Valores inválidos no posto %s (%s) — posto será "
                    "omitido dos cálculos (degradação)",
                    posto,
                    err,
                )
        return calculos

    # ------------------------------------------------------------------
    # Cache persistente (camada 3)
    # ------------------------------------------------------------------
    async def _async_carregar_cache(self) -> _CacheDados | None:
        """Carrega e valida o cache persistente do Store."""
        dados = await self._store.async_load()
        if not isinstance(dados, dict):
            _LOGGER.debug("Sem cache persistente para %s", self._filtro.distribuidora)
            return None
        if dados.get("filtro") != asdict(self._filtro):
            _LOGGER.debug("Cache ignorado: a configuração da entry mudou")
            return None
        try:
            tarifa = (
                TarifaData.from_dict(dados["tarifa"]) if dados.get("tarifa") else None
            )
            bandeira = (
                BandeiraData.from_dict(dados["bandeira"])
                if dados.get("bandeira")
                else None
            )
            bruto = dados.get("ultima_atualizacao_real")
            ultima = datetime.fromisoformat(bruto) if bruto else None
            if ultima is not None and ultima.tzinfo is None:
                # Cache legado/corrompido sem timezone: assume UTC.
                ultima = ultima.replace(tzinfo=UTC)
        except (KeyError, TypeError, ValueError) as err:
            _LOGGER.warning("Cache corrompido, será reconstruído: %s", err)
            return None
        return _CacheDados(
            tarifa=tarifa,
            bandeira=bandeira,
            ultima_atualizacao_real=ultima,
        )

    async def _async_salvar_cache(self, dados: DadosAneel) -> None:
        """Persiste dados e o timestamp da última atualização real."""
        payload: dict[str, Any] = {
            "versao": STORE_VERSION,
            "filtro": asdict(self._filtro),
            "tarifa": dados.tarifa.to_dict() if dados.tarifa else None,
            "bandeira": dados.bandeira.to_dict() if dados.bandeira else None,
            "ultima_atualizacao_real": (
                dados.ultima_atualizacao_real.isoformat()
                if dados.ultima_atualizacao_real
                else None
            ),
        }
        await self._store.async_save(payload)
        _LOGGER.debug(
            "Cache persistido (tarifa=%s, bandeira=%s, última real=%s)",
            dados.fonte_tarifa,
            dados.fonte_bandeira,
            dados.ultima_atualizacao_real,
        )

    # ------------------------------------------------------------------
    # Repair issue (> 7 dias só com cache)
    # ------------------------------------------------------------------
    async def _async_gerenciar_repair(
        self, dados: DadosAneel, agora: datetime
    ) -> None:
        """Abre/fecha o repair issue de dados somente de cache."""
        issue_id = f"{REPAIR_ISSUE_CACHE}_{self._entry.entry_id}"
        ultima = dados.ultima_atualizacao_real
        problema = (
            ultima is not None
            and (agora - ultima) > timedelta(days=REPAIR_CACHE_MAX_AGE_DAYS)
        )
        if problema and ultima is not None:
            dias = int((agora - ultima).total_seconds() // 86400)
            _LOGGER.warning(
                "Mais de %d dias sem atualização real (última: %s) — abrindo "
                "repair issue",
                REPAIR_CACHE_MAX_AGE_DAYS,
                ultima.isoformat(),
            )
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                is_persistent=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key="dados_apenas_cache",
                translation_placeholders={
                    "dias": str(dias),
                    "ultima": ultima.isoformat(),
                    "distribuidora": self._filtro.distribuidora,
                },
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
