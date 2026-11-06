"""Testes da Fase 2: diagnóstico, idade do dado e configuração do dispositivo.

As entidades usam um coordinator mínimo (``SimpleNamespace``), o mesmo
padrão de ``test_entidades.py``: validamos valores/atributos, não o ciclo
de vida do Home Assistant.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from homeassistant.const import EntityCategory, UnitOfTime

from custom_components.tarifas_aneel.api import TarifaFiltro
from custom_components.tarifas_aneel.button import LimparCacheAtualizarButton
from custom_components.tarifas_aneel.const import (
    ATTR_ULTIMA_ATUALIZACAO_SUCESSO,
    ATTR_ULTIMO_ERRO,
    CONF_DISTRIBUIDORA,
    CONF_MODALIDADE,
    CONF_SUBGRUPO,
)
from custom_components.tarifas_aneel.coordinator import AneelTarifasCoordinator
from custom_components.tarifas_aneel.models import (
    BandeiraData,
    FonteDado,
    PostoTarifa,
    ResultadoCalculo,
    TarifaData,
)
from custom_components.tarifas_aneel.sensor import (
    IdadeDadoSensor,
    TarifaFinalSensor,
    UltimaAtualizacaoSensor,
)

FILTRO = TarifaFiltro(
    distribuidora="EMS",
    subgrupo="B1",
    modalidade="Convencional",
    classe="Residencial",
    subclasse="Residencial",
)

ENTRY = SimpleNamespace(
    entry_id="entry_ems",
    options={},
    data={
        CONF_DISTRIBUIDORA: "EMS",
        CONF_SUBGRUPO: "B1",
        CONF_MODALIDADE: "Convencional",
    },
)

ULTIMA_REAL = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)

CALCULO = ResultadoCalculo(
    tarifa_te=0.31696,
    tarifa_tusd=0.47242,
    tarifa_sem_impostos=0.78938,
    adicional_bandeira=0.05,
    tarifa_com_bandeira=0.83938,
    tarifa_com_impostos=1.0,
    tarifa_final=1.1,
)


def _tarifa() -> TarifaData:
    """Tarifa de teste em R$/kWh."""
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


def _dados(ultima: datetime | None = ULTIMA_REAL):
    """Payload publicado pelo coordinator."""
    from custom_components.tarifas_aneel.coordinator import DadosAneel

    return DadosAneel(
        filtro=FILTRO,
        tarifa=_tarifa(),
        bandeira=_bandeira(),
        fonte_tarifa=FonteDado.API,
        fonte_bandeira=FonteDado.API,
        ultima_atualizacao_real=ultima,
        calculos={"Não se aplica": CALCULO},
    )


def _coord(
    dados: Any,
    *,
    ultimo_erro: str | None = None,
    hass: Any = None,
) -> SimpleNamespace:
    """Coordinator mínimo consumido pelas entidades."""
    return SimpleNamespace(
        data=dados,
        last_update_success=True,
        ultimo_erro=ultimo_erro,
        ultima_atualizacao_real=dados.ultima_atualizacao_real,
        hass=hass,
    )


def test_atributos_de_diagnostico_ultimo_erro_e_atualizacao() -> None:
    """Preços expõem o último erro e a última atualização real."""
    coord = _coord(_dados(), ultimo_erro="Falha nas 3 camadas")
    sensor = TarifaFinalSensor(coord, ENTRY)

    attrs = sensor.extra_state_attributes

    assert attrs[ATTR_ULTIMO_ERRO] == "Falha nas 3 camadas"
    assert attrs[ATTR_ULTIMA_ATUALIZACAO_SUCESSO] == ULTIMA_REAL.isoformat()


def test_sensor_de_ultima_atualizacao_expoe_ultimo_erro() -> None:
    """O sensor de diagnóstico também detalha o último erro."""
    coord = _coord(_dados(), ultimo_erro="Timeout na ANEEL")
    sensor = UltimaAtualizacaoSensor(coord, ENTRY)

    attrs = sensor.extra_state_attributes

    assert sensor.native_value == ULTIMA_REAL
    assert attrs[ATTR_ULTIMO_ERRO] == "Timeout na ANEEL"
    assert attrs[ATTR_ULTIMA_ATUALIZACAO_SUCESSO] == ULTIMA_REAL.isoformat()


def test_ultimo_erro_e_texto_curto_e_limpo_no_sucesso() -> None:
    """O coordinator guarda só a primeira linha do erro e limpa ao recuperar."""
    coordinator = object.__new__(AneelTarifasCoordinator)
    coordinator._ultimo_erro = None

    coordinator._registrar_erro(RuntimeError("primeira linha\nsegunda linha"))
    assert coordinator.ultimo_erro == "primeira linha"

    coordinator._registrar_erro(RuntimeError("x" * 500))
    assert coordinator.ultimo_erro is not None
    assert len(coordinator.ultimo_erro) <= 200

    coordinator._limpar_erro()
    assert coordinator.ultimo_erro is None


def test_sensor_idade_do_dado_em_dias() -> None:
    """A idade do dado é a diferença em dias desde a última atualização real."""
    ultima = datetime.now(UTC) - timedelta(days=2, hours=12)
    coord = _coord(_dados(ultima))

    sensor = IdadeDadoSensor(coord, ENTRY)

    assert sensor.native_value == 2.5
    assert sensor.native_unit_of_measurement == UnitOfTime.DAYS
    assert sensor.device_class == "duration"
    assert sensor.entity_category is EntityCategory.DIAGNOSTIC
    assert sensor.available is True


def test_sensor_idade_do_dado_sem_atualizacao_fica_indisponivel() -> None:
    """Sem dado real, a idade não é inventada."""
    coord = _coord(_dados(ultima=None))

    sensor = IdadeDadoSensor(coord, ENTRY)

    assert sensor.native_value is None
    assert sensor.available is False


def test_botao_limpar_cache_e_atualizar() -> None:
    """O botão limpa o cache persistente e força uma busca real."""
    chamadas: list[str] = []

    async def limpar_cache() -> None:
        chamadas.append("limpar")

    async def refresh() -> None:
        chamadas.append("refresh")

    coord = _coord(_dados())
    coord.async_limpar_cache = limpar_cache
    coord.async_refresh = refresh

    botao = LimparCacheAtualizarButton(coord, ENTRY)
    asyncio.run(botao.async_press())

    assert chamadas == ["limpar", "refresh"]
    assert botao.translation_key == "limpar_cache_atualizar"


def test_dispositivo_recebe_sufixo_quando_distribuidora_repetida() -> None:
    """Duas entries da mesma distribuidora não ficam com o mesmo nome."""
    outra = SimpleNamespace(
        entry_id="entry_ems_2",
        options={},
        data={
            CONF_DISTRIBUIDORA: "EMS",
            CONF_SUBGRUPO: "B1",
            CONF_MODALIDADE: "Branca",
        },
    )
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_entries=lambda domain: [ENTRY, outra]
        )
    )
    coord = _coord(_dados(), hass=hass)

    sensor = TarifaFinalSensor(coord, ENTRY)

    assert sensor.device_info["name"] == (
        "Energisa Mato Grosso do Sul (B1 • Convencional)"
    )
    assert sensor.device_info["model"] == "B1 • Convencional"


def test_dispositivo_sem_sufixo_com_uma_entry() -> None:
    """Com uma única entry, o nome do dispositivo continua limpo."""
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_entries=lambda domain: [ENTRY]
        )
    )
    coord = _coord(_dados(), hass=hass)

    sensor = TarifaFinalSensor(coord, ENTRY)

    assert sensor.device_info["name"] == "Energisa Mato Grosso do Sul"


def _traducoes() -> dict[str, dict[str, Any]]:
    """Carrega a seção ``entity`` das três traduções."""
    pasta = Path(__file__).resolve().parents[1] / "custom_components" / (
        "tarifas_aneel"
    )
    arquivos = [
        pasta / "strings.json",
        pasta / "translations" / "pt-BR.json",
        pasta / "translations" / "en.json",
    ]
    return {
        arquivo.name: json.loads(arquivo.read_text(encoding="utf-8"))["entity"]
        for arquivo in arquivos
    }


def test_traducoes_dos_novos_itens() -> None:
    """Idade do dado e botão de limpar cache existem em pt-BR e en."""
    traducoes = _traducoes()

    for nome, entidade in traducoes.items():
        assert "idade_dado" in entidade["sensor"], nome
        assert "limpar_cache_atualizar" in entidade["button"], nome

    assert traducoes["pt-BR.json"]["sensor"]["idade_dado"]["name"] == (
        "Idade do dado"
    )
    assert traducoes["pt-BR.json"]["button"]["limpar_cache_atualizar"][
        "name"
    ] == "Limpar cache e atualizar"
    assert traducoes["en.json"]["sensor"]["idade_dado"]["name"] == "Data age"
    assert traducoes["en.json"]["button"]["limpar_cache_atualizar"][
        "name"
    ] == "Clear cache and update"


def test_atributos_de_diagnostico_sem_coordenador_completo() -> None:
    """Coordinator mínimo sem os novos campos não quebra os atributos."""
    coord = SimpleNamespace(data=_dados(), last_update_success=True)
    sensor = TarifaFinalSensor(coord, ENTRY)

    attrs = sensor.extra_state_attributes

    assert attrs[ATTR_ULTIMO_ERRO] is None
    assert attrs[ATTR_ULTIMA_ATUALIZACAO_SUCESSO] == ULTIMA_REAL.isoformat()
