"""Testes de serialização dos modelos (:mod:`custom_components.tarifas_aneel.models`).

O roundtrip ``to_dict -> from_dict`` precisa ser identidade: o coordinator
persiste esses dicionários no :class:`Store` e recompõe na próxima sessão.
Amostras espelham os registros reais da ANEEL (Fase 0).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from custom_components.tarifas_aneel.models import (
    BandeiraData,
    FonteDado,
    PostoTarifa,
    ResultadoCalculo,
    TarifaData,
)


def _tarifa_convencional() -> TarifaData:
    """Registro real-like: Eletropaulo B1 Convencional Residencial."""
    return TarifaData(
        distribuidora="EPDP",
        subgrupo="B1",
        modalidade="Convencional",
        classe="Residencial",
        subclasse="Residencial",
        detalhe="Não se aplica",
        cnpj="61116265000144",
        reh="SCEE-XX",
        gerado_em=date(2026, 7, 4),
        inicio_vigencia=date(2026, 7, 4),
        fim_vigencia=date(2027, 7, 3),
        postos={
            "Não se aplica": PostoTarifa(
                posto="Não se aplica", tusd=0.47242, te=0.31696
            )
        },
        fonte=FonteDado.API,
        consultado_em=datetime(2026, 10, 28, 12, 0, tzinfo=UTC),
    )


def _tarifa_branca() -> TarifaData:
    """Registro Branca com os três postos do Grupo B."""
    return TarifaData(
        distribuidora="EPDP",
        subgrupo="B1",
        modalidade="Branca",
        classe="Residencial",
        subclasse=None,
        detalhe="Não se aplica",
        inicio_vigencia=date(2026, 7, 4),
        fim_vigencia=None,
        postos={
            "Ponta": PostoTarifa(posto="Ponta", tusd=0.7, te=0.5),
            "Intermediário": PostoTarifa(posto="Intermediário", tusd=0.6, te=0.4),
            "Fora ponta": PostoTarifa(posto="Fora ponta", tusd=0.5, te=0.3),
        },
        fonte=FonteDado.CSV,
    )


def test_fonte_dado_valores() -> None:
    """StrEnum da fonte persistida como texto do payload."""
    assert FonteDado.API.value == "API"
    assert FonteDado.CSV.value == "CSV"
    assert FonteDado.CACHE.value == "Cache"


@pytest.mark.parametrize(
    "tarifa", [_tarifa_convencional(), _tarifa_branca()], ids=["conv", "branca"]
)
def test_tarifa_data_roundtrip(tarifa: TarifaData) -> None:
    """to_dict -> from_dict devolve o modelo original sem perdas."""
    reconstruida = TarifaData.from_dict(tarifa.to_dict())
    assert reconstruida == tarifa


def test_tarifa_data_postos_seriais() -> None:
    """Os postos serializados preservam tusd/te em R$/kWh."""
    serializada = _tarifa_convencional().to_dict()
    posto_na_chave = serializada["postos"]["Não se aplica"]
    assert posto_na_chave == {
        "posto": "Não se aplica",
        "tusd": 0.47242,
        "te": 0.31696,
    }


def test_bandeira_data_roundtrip() -> None:
    """Roundtrip da bandeira com todos os campos preenchidos."""
    bandeira = BandeiraData(
        competencia=date(2026, 9, 1),
        nome="Amarela",
        adicional_rsmwh=5.0,
        adicional=0.005,
        fonte=FonteDado.API,
        consultado_em=datetime(2026, 10, 28, 12, 0, tzinfo=UTC),
        mes_anterior=True,
    )
    reconstruida = BandeiraData.from_dict(bandeira.to_dict())
    assert reconstruida == bandeira


def test_bandeira_data_defaults() -> None:
    """Campos opcionais ausentes no payload legado assumem o padrão."""
    reconstruida = BandeiraData.from_dict(
        {
            "competencia": "2026-10-01",
            "nome": "Verde",
            "adicional_rsmwh": 0.0,
            "adicional": 0.0,
            "fonte": "API",
        }
    )
    assert reconstruida.consultado_em is None
    assert reconstruida.mes_anterior is False


def test_resultado_calculo_campos_expostos() -> None:
    """ResultadoCalculo expõe exatamente os campos lidos por getattr."""
    campos = {f"tarifa_{t}" for t in ("te", "tusd", "sem_impostos")}
    campos |= {
        "adicional_bandeira",
        "tarifa_com_bandeira",
        "tarifa_com_impostos",
        "tarifa_final",
    }
    calculo = ResultadoCalculo(
        tarifa_te=0.1,
        tarifa_tusd=0.2,
        tarifa_sem_impostos=0.3,
        adicional_bandeira=0.0,
        tarifa_com_bandeira=0.3,
        tarifa_com_impostos=0.3,
        tarifa_final=0.3,
    )
    for nome in campos:
        assert getattr(calculo, nome) is not None
