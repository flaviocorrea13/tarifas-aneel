"""Testes das entidades: preço, vigência, diagnóstico e binary sensors.

As entidades são instanciadas com um coordinator falso (sem loop do Home
Assistant): o objetivo é validar nomes/unique_ids, DeviceInfo, valores e a
lógica dos indicadores, não o ciclo de vida do HA.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from homeassistant.const import EntityCategory
import pytest

from custom_components.tarifas_aneel.api import TarifaFiltro
from custom_components.tarifas_aneel.binary_sensor import (
    BandeiraVermelhaBinarySensor,
    StatusApiBinarySensor,
)
from custom_components.tarifas_aneel.const import (
    BANDEIRA_VERMELHA_P1,
    BANDEIRA_VERMELHA_P2,
    CONF_DISTRIBUIDORA,
    CONF_MODALIDADE,
    CONF_SUBGRUPO,
    DOMAIN,
)
from custom_components.tarifas_aneel.coordinator import DadosAneel
from custom_components.tarifas_aneel.models import (
    BandeiraData,
    FonteDado,
    PostoTarifa,
    ResultadoCalculo,
    TarifaData,
)
from custom_components.tarifas_aneel.sensor import (
    AdicionalBandeiraSensor,
    FonteDadoBandeiraSensor,
    FonteDadoTarifaSensor,
    TarifaComBandeiraSensor,
    TarifaComImpostosSensor,
    TarifaFinalSensor,
    TarifaSemImpostosSensor,
    TESensor,
    TUSDSensor,
    UltimaAtualizacaoSensor,
    VigenciaFimSensor,
    VigenciaInicioSensor,
)

FILTRO = TarifaFiltro(
    distribuidora="EMS",
    subgrupo="B1",
    modalidade="Convencional",
    classe="Residencial",
    subclasse="Residencial",
)

CALCULO = ResultadoCalculo(
    tarifa_te=0.31696,
    tarifa_tusd=0.47242,
    tarifa_sem_impostos=0.78938,
    adicional_bandeira=0.05,
    tarifa_com_bandeira=0.83938,
    tarifa_com_impostos=1.0,
    tarifa_final=1.1,
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


def _tarifa(fim_vigencia: date | None = date(2027, 7, 3)) -> TarifaData:
    """Tarifa de teste com vigência definida."""
    return TarifaData(
        distribuidora="EMS",
        subgrupo="B1",
        modalidade="Convencional",
        classe="Residencial",
        subclasse="Residencial",
        detalhe="Não se aplica",
        inicio_vigencia=date(2026, 7, 4),
        fim_vigencia=fim_vigencia,
        postos={
            "Não se aplica": PostoTarifa(
                posto="Não se aplica", tusd=0.47242, te=0.31696
            )
        },
        fonte=FonteDado.API,
    )


def _bandeira(
    nome: str = "Verde", fonte: FonteDado = FonteDado.API
) -> BandeiraData:
    """Bandeira de teste."""
    return BandeiraData(
        competencia=date(2026, 10, 1),
        nome=nome,
        adicional_rsmwh=0.0,
        adicional=0.0,
        fonte=fonte,
    )


def _dados(
    fonte_tarifa: FonteDado = FonteDado.API,
    fonte_bandeira: FonteDado = FonteDado.API,
    bandeira: BandeiraData | None = None,
    fim_vigencia: date | None = date(2027, 7, 3),
) -> DadosAneel:
    """Payload publicado pelo coordinator."""
    return DadosAneel(
        filtro=FILTRO,
        tarifa=_tarifa(fim_vigencia),
        bandeira=bandeira or _bandeira(),
        fonte_tarifa=fonte_tarifa,
        fonte_bandeira=fonte_bandeira,
        ultima_atualizacao_real=datetime(2026, 10, 30, 12, 0, tzinfo=UTC),
        calculos={"Não se aplica": CALCULO},
    )


def _coord(dados: DadosAneel) -> SimpleNamespace:
    """Coordinator mínimo consumido pelas entidades."""
    return SimpleNamespace(data=dados, last_update_success=True)


def test_device_info_segue_o_padrao_pedido() -> None:
    """Fabricante, nome amigável e modelo do dispositivo."""
    sensor = TarifaFinalSensor(_coord(_dados()), ENTRY)

    assert sensor.device_info["manufacturer"] == "Dados Abertos ANEEL"
    assert sensor.device_info["name"] == "Energisa Mato Grosso do Sul"
    assert sensor.device_info["model"] == "B1 • Convencional"
    assert sensor.device_info["identifiers"] == {(DOMAIN, "entry_ems")}


def test_unique_id_e_translation_key_das_novas_entidades() -> None:
    """Toda entidade usa o suffix como unique_id e translation_key."""
    coord = _coord(_dados())
    entidades = [
        TarifaComBandeiraSensor(coord, ENTRY),
        TarifaComImpostosSensor(coord, ENTRY),
        VigenciaInicioSensor(coord, ENTRY),
        VigenciaFimSensor(coord, ENTRY),
        FonteDadoTarifaSensor(coord, ENTRY),
        FonteDadoBandeiraSensor(coord, ENTRY),
        UltimaAtualizacaoSensor(coord, ENTRY),
        StatusApiBinarySensor(coord, ENTRY),
        BandeiraVermelhaBinarySensor(coord, ENTRY),
    ]
    for entidade in entidades:
        assert entidade.unique_id == f"entry_ems_{entidade.translation_key}"


def test_sensores_de_preco_intermediarios() -> None:
    """Preço com bandeira (sem impostos) e com impostos (sem bandeira)."""
    coord = _coord(_dados())

    com_bandeira = TarifaComBandeiraSensor(coord, ENTRY)
    com_impostos = TarifaComImpostosSensor(coord, ENTRY)

    assert com_bandeira.native_value == pytest.approx(0.83938)
    assert com_impostos.native_value == pytest.approx(1.0)
    # Os valores não se confundem com os sensores já existentes.
    assert TarifaFinalSensor(coord, ENTRY).native_value == pytest.approx(1.1)
    assert TarifaSemImpostosSensor(
        coord, ENTRY
    ).native_value == pytest.approx(0.78938)
    assert TUSDSensor(coord, ENTRY).native_value == pytest.approx(0.47242)
    assert TESensor(coord, ENTRY).native_value == pytest.approx(0.31696)
    assert AdicionalBandeiraSensor(
        coord, ENTRY
    ).native_value == pytest.approx(0.05)


def test_sensores_de_vigencia() -> None:
    """Início e fim da vigência como datas."""
    coord = _coord(_dados())

    inicio = VigenciaInicioSensor(coord, ENTRY)
    fim = VigenciaFimSensor(coord, ENTRY)

    assert inicio.native_value == date(2026, 7, 4)
    assert fim.native_value == date(2027, 7, 3)
    assert inicio.device_class == "date"
    assert fim.device_class == "date"
    assert inicio.available is True
    assert fim.available is True


def test_vigencia_fim_aberta_fica_indisponivel() -> None:
    """Vigência sem data final não inventa valor."""
    coord = _coord(_dados(fim_vigencia=None))
    fim = VigenciaFimSensor(coord, ENTRY)

    assert fim.native_value is None
    assert fim.available is False


def test_fontes_de_dados_sao_diagnostico() -> None:
    """Origem da tarifa e da bandeira com categoria diagnostic."""
    coord = _coord(_dados(FonteDado.CSV, FonteDado.CACHE))

    fonte_tarifa = FonteDadoTarifaSensor(coord, ENTRY)
    fonte_bandeira = FonteDadoBandeiraSensor(coord, ENTRY)

    assert fonte_tarifa.native_value == "CSV"
    assert fonte_bandeira.native_value == "Cache"
    assert fonte_tarifa.entity_category is EntityCategory.DIAGNOSTIC
    assert fonte_bandeira.entity_category is EntityCategory.DIAGNOSTIC


def test_ultima_atualizacao_e_timestamp_de_diagnostico() -> None:
    """Timestamp da última atualização real e origens nos atributos."""
    coord = _coord(_dados(FonteDado.CSV, FonteDado.API))
    sensor = UltimaAtualizacaoSensor(coord, ENTRY)

    assert sensor.native_value == datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    assert sensor.device_class == "timestamp"
    assert sensor.entity_category is EntityCategory.DIAGNOSTIC
    assert sensor.extra_state_attributes == {
        "fonte_tarifa": "CSV",
        "fonte_bandeira": "API",
    }


def test_status_api_ligado_so_com_as_duas_fontes_api() -> None:
    """Status API: ligado somente quando tarifa e bandeira são API."""
    api = StatusApiBinarySensor(
        _coord(_dados(FonteDado.API, FonteDado.API)), ENTRY
    )
    fallback = StatusApiBinarySensor(
        _coord(_dados(FonteDado.CSV, FonteDado.CACHE)), ENTRY
    )

    assert api.is_on is True
    assert fallback.is_on is False
    assert fallback.extra_state_attributes == {
        "fonte_tarifa": "CSV",
        "fonte_bandeira": "Cache",
    }


@pytest.mark.parametrize(
    ("nome", "esperado"),
    [
        (BANDEIRA_VERMELHA_P1, True),
        (BANDEIRA_VERMELHA_P2, True),
        ("Amarela", False),
        ("Verde", False),
        ("Escassez Hídrica", False),
    ],
)
def test_bandeira_vermelha_ativa(nome: str, esperado: bool) -> None:
    """Só Vermelha P1/P2 ligam o indicador."""
    coord = _coord(_dados(bandeira=_bandeira(nome)))
    sensor = BandeiraVermelhaBinarySensor(coord, ENTRY)

    assert sensor.is_on is esperado
    assert sensor.available is True


def test_bandeira_vermelha_indisponivel_sem_bandeira() -> None:
    """Sem bandeira carregada o indicador não afirma nada."""
    dados = _dados()
    dados.bandeira = None
    sensor = BandeiraVermelhaBinarySensor(_coord(dados), ENTRY)

    assert sensor.available is False
    assert sensor.is_on is False


def _json_entidades() -> dict[str, Any]:
    """Carrega a seção ``entity`` das três traduções."""
    base = Path(__file__).resolve().parents[1] / "custom_components"
    pasta = base / "tarifas_aneel"
    arquivos = [
        pasta / "strings.json",
        pasta / "translations" / "pt-BR.json",
        pasta / "translations" / "en.json",
    ]
    return {
        str(arquivo): json.loads(arquivo.read_text(encoding="utf-8"))["entity"]
        for arquivo in arquivos
    }


def test_traducoes_tem_todas_as_entidades() -> None:
    """As três traduções declaram os mesmos translation_keys."""
    sensores = {
        "tarifa_final",
        "tarifa_sem_impostos",
        "tarifa_com_bandeira",
        "tarifa_com_impostos",
        "tarifa_tusd",
        "tarifa_te",
        "adicional_bandeira",
        "bandeira_atual",
        "posto_tarifario",
        "vigencia_inicio",
        "vigencia_fim",
        "fonte_dado_tarifa",
        "fonte_dado_bandeira",
        "ultima_atualizacao_sucesso",
        "custo_fixo_mensal",
        "custo_estimado_ciclo",
    }
    binarios = {
        "dados_desatualizados",
        "status_api",
        "bandeira_vermelha_ativa",
    }

    for arquivo, entidade in _json_entidades().items():
        assert set(entidade["sensor"]) == sensores, arquivo
        assert set(entidade["binary_sensor"]) == binarios, arquivo
