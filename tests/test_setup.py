"""Testes do setup em duas fases, backoff e reload por opções.

Sem o harness do Home Assistant: o coordinator é substituído por um fake
para validar a fiação do ``async_setup_entry`` (cache -> busca real em
segundo plano) e o backoff é exercitado com ``asyncio.sleep`` simulado.
"""

from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from custom_components.tarifas_aneel import (
    CHAVE_DADOS_RELOAD,
    async_setup_entry,
)
from custom_components.tarifas_aneel.api import TarifaFiltro
from custom_components.tarifas_aneel.binary_sensor import StatusApiBinarySensor
from custom_components.tarifas_aneel.const import (
    CONF_CLASSE,
    CONF_DETALHE,
    CONF_DISTRIBUIDORA,
    CONF_MODALIDADE,
    CONF_SUBCLASSE,
    CONF_SUBGRUPO,
    DOMAIN,
    OPT_COFINS,
    OPT_ICMS,
    OPT_PIS,
)
from custom_components.tarifas_aneel.coordinator import (
    AneelTarifasCoordinator,
    DadosAneel,
)
from custom_components.tarifas_aneel.models import (
    BandeiraData,
    FonteDado,
    PostoTarifa,
    ResultadoCalculo,
    TarifaData,
)

FILTRO = TarifaFiltro(
    distribuidora="EMS",
    subgrupo="B1",
    modalidade="Convencional",
    classe="Residencial",
    subclasse="Residencial",
)

CALCULO_ANTIGO = ResultadoCalculo(
    tarifa_te=0.31696,
    tarifa_tusd=0.47242,
    tarifa_sem_impostos=0.78938,
    adicional_bandeira=0.05,
    tarifa_com_bandeira=0.83938,
    tarifa_com_impostos=1.0,
    tarifa_final=1.1,
)


class _EntryFalso:
    """ConfigEntry mínima usada pelo setup."""

    def __init__(self) -> None:
        self.entry_id = "entry_setup"
        self.data = {
            CONF_DISTRIBUIDORA: "EMS",
            CONF_SUBGRUPO: "B1",
            CONF_MODALIDADE: "Convencional",
            CONF_CLASSE: "Residencial",
            CONF_SUBCLASSE: "Residencial",
            CONF_DETALHE: "Não se aplica",
        }
        self.options: dict[str, Any] = {}
        self.runtime_data = None
        self.tarefas: list[asyncio.Task[Any]] = []
        self.on_unload: Any = None
        self.update_listener: Any = None

    def async_create_background_task(
        self, hass: _HassFalso, target: Any, name: str
    ) -> asyncio.Task[Any]:
        """Agenda a tarefa de segundo plano como o HA faria."""
        tarefa = hass.async_create_background_task(target, name)
        self.tarefas.append(tarefa)
        return tarefa

    def async_on_unload(self, callback: Any) -> None:
        """Guarda o callback de unload."""
        self.on_unload = callback

    def add_update_listener(self, callback: Any) -> Any:
        """Guarda o listener de opções e devolve o cancelador."""
        self.update_listener = callback
        return lambda: None


class _HassFalso:
    """HomeAssistant mínimo para o setup (sem rede e sem plataformas)."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.config_entries = SimpleNamespace(
            async_forward_entry_setups=self._forward
        )
        self.plataformas: list[Any] = []
        self.tarefas: list[asyncio.Task[Any]] = []

    async def _forward(self, entry: Any, plataformas: list[Any]) -> None:
        self.plataformas = list(plataformas)

    def async_create_background_task(
        self, target: Any, name: str, eager_start: bool = True
    ) -> asyncio.Task[Any]:
        """Cria a tarefa no loop (equivale ao eager start do HA)."""
        tarefa = asyncio.ensure_future(target)
        self.tarefas.append(tarefa)
        return tarefa


class _CoordinatorFalso:
    """Coordinator que simula cache publicado e API logo em seguida."""

    instancias: ClassVar[list[_CoordinatorFalso]] = []

    def __init__(self, hass: Any, entry: Any, filtro: TarifaFiltro) -> None:
        self.hass = hass
        self.entry = entry
        self.filtro = filtro
        self.data: DadosAneel | None = None
        self.cache_publicado = False
        self.refresh_chamado = False
        self.cache_antes_do_refresh: FonteDado | None = None
        self.aplicar_chamado = False
        self.primeiro_refresh_chamado = False
        _CoordinatorFalso.instancias.append(self)

    async def async_carregar_cache_inicial(self) -> bool:
        """Publica o cache (fonte Cache) antes das plataformas."""
        self.data = _dados(FonteDado.CACHE)
        self.cache_publicado = True
        return True

    async def async_refresh_com_backoff(self) -> None:
        """Simula a busca real bem-sucedida (fonte API)."""
        self.refresh_chamado = True
        self.cache_antes_do_refresh = (
            self.data.fonte_tarifa if self.data is not None else None
        )
        self.data = _dados(FonteDado.API)

    async def async_config_entry_first_refresh(self) -> None:
        """Não deve ser usado quando há cache."""
        self.primeiro_refresh_chamado = True

    def async_set_updated_data(self, dados: DadosAneel) -> None:
        """Publica o payload como o coordinator real."""
        self.data = dados

    @property
    def tem_fonte_real(self) -> bool:
        """O payload atual veio de API ou CSV?"""
        if self.data is None:
            return False
        fontes = (FonteDado.API, FonteDado.CSV)
        return (
            self.data.fonte_tarifa in fontes
            or self.data.fonte_bandeira in fontes
        )

    def aplicar_opcoes(self) -> None:
        """Marca que o reload apenas reaplicou as opções."""
        self.aplicar_chamado = True


def _tarifa() -> TarifaData:
    """Tarifa de teste."""
    return TarifaData(
        distribuidora="EMS",
        subgrupo="B1",
        modalidade="Convencional",
        classe="Residencial",
        subclasse="Residencial",
        detalhe="Não se aplica",
        inicio_vigencia=date(2026, 7, 4),
        fim_vigencia=date(2027, 7, 3),
        postos={
            "Não se aplica": PostoTarifa(
                posto="Não se aplica", tusd=0.47242, te=0.31696
            )
        },
        fonte=FonteDado.API,
    )


def _bandeira() -> BandeiraData:
    """Bandeira de teste."""
    return BandeiraData(
        competencia=date(2026, 10, 1),
        nome="Verde",
        adicional_rsmwh=0.0,
        adicional=0.0,
        fonte=FonteDado.API,
    )


def _dados(fonte: FonteDado) -> DadosAneel:
    """Payload com a fonte informada (API ou Cache)."""
    return DadosAneel(
        filtro=FILTRO,
        tarifa=_tarifa(),
        bandeira=_bandeira(),
        fonte_tarifa=fonte,
        fonte_bandeira=fonte,
        calculos={"Não se aplica": CALCULO_ANTIGO},
    )


def _coordinator_de_backoff() -> AneelTarifasCoordinator:
    """Coordinator real sem ``__init__`` (sem loop/Store)."""
    coordinator = object.__new__(AneelTarifasCoordinator)
    coordinator._filtro = FILTRO
    coordinator.last_update_success = False
    return coordinator


def test_setup_com_cache_agenda_busca_real_e_status_api_liga(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cache é publicado e a API o substitui em segundo plano."""
    monkeypatch.setattr(
        "custom_components.tarifas_aneel.AneelTarifasCoordinator",
        _CoordinatorFalso,
    )
    _CoordinatorFalso.instancias.clear()
    entry = _EntryFalso()
    hass = _HassFalso()

    async def cenario() -> None:
        await async_setup_entry(hass, entry)  # type: ignore[arg-type]
        await asyncio.gather(*entry.tarefas)

    asyncio.run(cenario())

    coordinator = entry.runtime_data
    assert coordinator is not None
    assert coordinator.cache_publicado is True
    assert coordinator.refresh_chamado is True
    assert coordinator.primeiro_refresh_chamado is False
    # A busca real partiu de um payload Cache e terminou em API.
    assert coordinator.cache_antes_do_refresh is FonteDado.CACHE
    assert coordinator.data is not None
    assert coordinator.data.fonte_tarifa is FonteDado.API
    assert coordinator.data.fonte_bandeira is FonteDado.API

    status = StatusApiBinarySensor(coordinator, entry)
    assert status.is_on is True
    assert status.extra_state_attributes == {
        "fonte_tarifa": "API",
        "fonte_bandeira": "API",
    }
    assert hass.plataformas


def test_reload_preserva_fonte_api_e_nao_busca_na_rede(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reload reusa o payload real e apenas reaplica as opções."""
    monkeypatch.setattr(
        "custom_components.tarifas_aneel.AneelTarifasCoordinator",
        _CoordinatorFalso,
    )
    _CoordinatorFalso.instancias.clear()
    entry = _EntryFalso()
    hass = _HassFalso()
    payload = _dados(FonteDado.API)
    hass.data[DOMAIN] = {
        f"{CHAVE_DADOS_RELOAD}_{entry.entry_id}": payload
    }

    asyncio.run(async_setup_entry(hass, entry))  # type: ignore[arg-type]

    coordinator = entry.runtime_data
    assert coordinator is not None
    assert coordinator.aplicar_chamado is True
    assert coordinator.cache_publicado is False
    assert coordinator.refresh_chamado is False
    assert coordinator.primeiro_refresh_chamado is False
    assert entry.tarefas == []
    assert coordinator.data is payload
    assert coordinator.data.fonte_tarifa is FonteDado.API
    assert coordinator.data.fonte_bandeira is FonteDado.API
    # O payload guardado é consumido uma única vez.
    assert f"{CHAVE_DADOS_RELOAD}_{entry.entry_id}" not in hass.data[DOMAIN]


def test_reload_com_payload_cache_reagenda_busca_real(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reload ainda em Cache não fica preso até o update_interval."""
    monkeypatch.setattr(
        "custom_components.tarifas_aneel.AneelTarifasCoordinator",
        _CoordinatorFalso,
    )
    _CoordinatorFalso.instancias.clear()
    entry = _EntryFalso()
    hass = _HassFalso()
    payload = _dados(FonteDado.CACHE)
    hass.data[DOMAIN] = {
        f"{CHAVE_DADOS_RELOAD}_{entry.entry_id}": payload
    }

    async def cenario() -> None:
        await async_setup_entry(hass, entry)  # type: ignore[arg-type]
        await asyncio.gather(*entry.tarefas)

    asyncio.run(cenario())

    coordinator = entry.runtime_data
    assert coordinator is not None
    assert coordinator.aplicar_chamado is True
    assert coordinator.cache_publicado is False
    # Reaproveitou o payload Cache e buscou a API logo em seguida.
    assert coordinator.refresh_chamado is True
    assert len(entry.tarefas) == 1
    assert coordinator.data is not None
    assert coordinator.data.fonte_tarifa is FonteDado.API
    assert StatusApiBinarySensor(coordinator, entry).is_on is True


def test_aplicar_opcoes_recalcula_sem_trocar_a_fonte() -> None:
    """Novas alíquotas mudam só o cálculo; a fonte original permanece."""
    coordinator = object.__new__(AneelTarifasCoordinator)
    coordinator._entry = SimpleNamespace(
        entry_id="entry_setup",
        options={OPT_ICMS: 18.0, OPT_PIS: 1.65, OPT_COFINS: 7.6},
        data={},
    )
    coordinator._filtro = FILTRO
    coordinator._opcoes_entidades = coordinator._entidades_opcoes()
    coordinator.update_interval = None
    coordinator.data = _dados(FonteDado.API)
    coordinator.async_set_updated_data = lambda dados: setattr(
        coordinator, "data", dados
    )

    coordinator.aplicar_opcoes()

    dados = coordinator.data
    assert dados.fonte_tarifa is FonteDado.API
    assert dados.fonte_bandeira is FonteDado.API
    calculo = dados.calculos["Não se aplica"]
    assert calculo != CALCULO_ANTIGO
    assert calculo.adicional_bandeira == 0.0
    assert calculo.tarifa_final > calculo.tarifa_sem_impostos


def test_backoff_repetem_em_5_15_e_60_minutos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Falha em todas as tentativas agenda 5, 15 e 60 minutos."""
    coordinator = _coordinator_de_backoff()
    resultados = iter([False, False, False, False])
    tentativas: list[int] = []
    esperas: list[int] = []

    async def refresh() -> None:
        tentativas.append(1)
        coordinator.last_update_success = next(resultados)

    async def sleep(segundos: float) -> None:
        esperas.append(int(segundos))

    coordinator.async_refresh = refresh  # type: ignore[method-assign]
    monkeypatch.setattr(
        "custom_components.tarifas_aneel.coordinator.asyncio.sleep", sleep
    )

    asyncio.run(coordinator.async_refresh_com_backoff())

    assert len(tentativas) == 4
    assert esperas == [5 * 60, 15 * 60, 60 * 60]


def test_backoff_continua_quando_o_refresh_publica_apenas_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cache publicado com "sucesso" não encerra o backoff."""
    coordinator = _coordinator_de_backoff()
    respostas = iter(
        [(True, FonteDado.CACHE), (True, FonteDado.API)]
    )
    tentativas: list[int] = []
    esperas: list[int] = []

    async def refresh() -> None:
        tentativas.append(1)
        sucesso, fonte = next(respostas)
        coordinator.last_update_success = sucesso
        coordinator.data = _dados(fonte)

    async def sleep(segundos: float) -> None:
        esperas.append(int(segundos))

    coordinator.async_refresh = refresh  # type: ignore[method-assign]
    monkeypatch.setattr(
        "custom_components.tarifas_aneel.coordinator.asyncio.sleep", sleep
    )

    asyncio.run(coordinator.async_refresh_com_backoff())

    assert len(tentativas) == 2
    assert esperas == [5 * 60]


def test_backoff_para_na_primeira_busca_bem_sucedida(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sem falha, não agenda retentativa."""
    coordinator = _coordinator_de_backoff()
    tentativas: list[int] = []
    esperas: list[int] = []

    async def refresh() -> None:
        tentativas.append(1)
        coordinator.last_update_success = True
        coordinator.data = _dados(FonteDado.API)

    async def sleep(segundos: float) -> None:
        esperas.append(int(segundos))

    coordinator.async_refresh = refresh  # type: ignore[method-assign]
    monkeypatch.setattr(
        "custom_components.tarifas_aneel.coordinator.asyncio.sleep", sleep
    )

    asyncio.run(coordinator.async_refresh_com_backoff())

    assert len(tentativas) == 1
    assert esperas == []


def test_backoff_para_quando_recupera(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Depois de duas falhas, a terceira tentativa encerra o backoff."""
    coordinator = _coordinator_de_backoff()
    resultados = iter([False, False, True])
    tentativas: list[int] = []
    esperas: list[int] = []

    async def refresh() -> None:
        tentativas.append(1)
        coordinator.last_update_success = next(resultados)
        coordinator.data = _dados(
            FonteDado.API
            if coordinator.last_update_success
            else FonteDado.CACHE
        )

    async def sleep(segundos: float) -> None:
        esperas.append(int(segundos))

    coordinator.async_refresh = refresh  # type: ignore[method-assign]
    monkeypatch.setattr(
        "custom_components.tarifas_aneel.coordinator.asyncio.sleep", sleep
    )

    asyncio.run(coordinator.async_refresh_com_backoff())

    assert len(tentativas) == 3
    assert esperas == [5 * 60, 15 * 60]
