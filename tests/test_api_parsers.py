"""Testes dos parsers puros de :mod:`custom_components.tarifas_aneel.api`.

Importar :mod:`api` exige ``aiohttp`` + ``homeassistant`` instalados; sem
eles os testes são pulados (rodam integralmente no CI, que instala o HA
2024.10). As amostras espelham os payloads reais do CKAN da Fase 0.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

pytest.importorskip("homeassistant")

from custom_components.tarifas_aneel.api import (
    AneelApiError,
    TarifaFiltro,
    parse_bandeira_records,
    parse_data_iso,
    parse_tarifa_records,
    parse_valor_br,
)
from custom_components.tarifas_aneel.const import BASE_TARIFARIA_APLICACAO
from custom_components.tarifas_aneel.models import FonteDado

FILTERS_ESPERADOS: dict[str, str] = {
    "SigAgente": "EPDP",
    "DscBaseTarifaria": BASE_TARIFARIA_APLICACAO,
    "DscSubGrupo": "B1",
    "DscModalidadeTarifaria": "Convencional",
    "DscClasse": "Residencial",
    "DscSubClasse": "Residencial",
    "DscDetalhe": "Não se aplica",
    "SigAgenteAcessante": "Não se aplica",
}


def test_filtro_to_filters() -> None:
    """Parâmetro ``filters`` do datastore_search (grafias da Fase 0)."""
    filtro = TarifaFiltro(
        distribuidora="EPDP",
        subgrupo="B1",
        modalidade="Convencional",
        classe="Residencial",
        subclasse="Residencial",
    )
    assert filtro.to_filters() == FILTERS_ESPERADOS


# ---------------------------------------------------------------------------
# parse_valor_br
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("472,42", 472.42),
        (",00", 0.0),
        ("0,00", 0.0),
        ("316,96", 316.96),
        (" 472,42 ", 472.42),
        ("R$ 10,00", 10.0),
        ("R$10,00", 10.0),
        ("1.234,56", 1234.56),
        ("37.21", 37.21),
        ("1.234", 1234.0),
        ("1.23", 1.23),
        ("1234,5", 1234.5),
        ("-5,00", -5.0),
    ],
)
def test_parse_valor_br(texto: str, esperado: float) -> None:
    """Formato brasileiro (vírgula decimal) e tolerância a \"R$\"/espaços."""
    assert parse_valor_br(texto) == pytest.approx(esperado)


@pytest.mark.parametrize("texto", [None, "", "   "])
def test_parse_valor_br_invalido(texto: str | None) -> None:
    """Vazio/ausente levanta ``ValueError`` (linha malformada)."""
    with pytest.raises(ValueError):
        parse_valor_br(texto)


# ---------------------------------------------------------------------------
# parse_data_iso
# ---------------------------------------------------------------------------
def test_parse_data_iso() -> None:
    """Datas ISO do dataset (DatInicioVigencia/DatFimVigencia)."""
    assert parse_data_iso("2026-07-04") == date(2026, 7, 4)
    assert parse_data_iso(" 2026-07-04 ") == date(2026, 7, 4)


@pytest.mark.parametrize("texto", [None, "", "   ", "04/07/2026", "2026-13-01"])
def test_parse_data_iso_invalido(texto: str | None) -> None:
    """Ausente/malformada levanta ``ValueError``."""
    with pytest.raises(ValueError):
        parse_data_iso(texto)


# ---------------------------------------------------------------------------
# parse_tarifa_records
# ---------------------------------------------------------------------------
def _registro_tarifa(
    id_: int,
    posto: str,
    tusd: str,
    te: str,
    inicio: str = "2026-07-04",
    fim: str | None = "2027-07-03",
    unidade: str = "MWh",
    acessante: str = "Não se aplica",
    agente: str = "EPDP",
) -> dict[str, object]:
    """Linha real-like do datastore (nomes de campo = API_FIELD_*)."""
    return {
        "_id": id_,
        "SigAgente": agente,
        "SigAgenteAcessante": acessante,
        "DscBaseTarifaria": BASE_TARIFARIA_APLICACAO,
        "NomPostoTarifario": posto,
        "DatInicioVigencia": inicio,
        "DatFimVigencia": fim,
        "DatGeracaoConjuntoDados": "2026-07-04",
        "DscSubGrupo": "B1",
        "DscModalidadeTarifaria": "Convencional",
        "DscClasse": "Residencial",
        "DscSubClasse": "Residencial",
        "DscDetalhe": "Não se aplica",
        "NumCNPJDistribuidora": "61116265000144",
        "DscREH": "1234567890",
        "DscUnidadeTerciaria": unidade,
        "VlrTUSD": tusd,
        "VlrTE": te,
    }


def test_parse_tarifa_convencional_agrupa() -> None:
    """Uma vigência, um posto \"Não se aplica\", valores em R$/kWh."""
    resultados = parse_tarifa_records(
        [_registro_tarifa(1, "", "472,42", "316,96")], FonteDado.CSV
    )
    assert len(resultados) == 1
    tarifa = resultados[0]
    assert tarifa.distribuidora == "EPDP"
    assert tarifa.subgrupo == "B1"
    assert tarifa.modalidade == "Convencional"
    assert tarifa.inicio_vigencia == date(2026, 7, 4)
    assert tarifa.fim_vigencia == date(2027, 7, 3)
    posto_na_chave = tarifa.postos["Não se aplica"]
    assert posto_na_chave.posto == "Não se aplica"
    assert posto_na_chave.tusd == pytest.approx(0.47242)
    assert posto_na_chave.te == pytest.approx(0.31696)


def test_parse_tarifa_branca_tres_postos_uma_vigencia() -> None:
    """Branca: três postos que compartilham vigência ficam num grupo só."""
    registros = [_registro_tarifa(1, "Ponta", "700,00", "500,00")]
    registros.append(_registro_tarifa(2, "Intermediário", "600,00", "400,00"))
    registros.append(_registro_tarifa(3, "Fora ponta", "500,00", "300,00"))
    resultados = parse_tarifa_records(registros, FonteDado.CSV)
    assert len(resultados) == 1
    assert set(resultados[0].postos) == {"Ponta", "Intermediário", "Fora ponta"}


def test_parse_tarifa_ordem_mais_recente_primeiro() -> None:
    """Duas vigências distintas, a mais nova vem antes (candidatos[0])."""
    registros = [_registro_tarifa(1, "", "40,00", "30,00", "2024-07-04")]
    registros.append(_registro_tarifa(2, "", "50,00", "35,00", "2025-07-04"))
    resultados = parse_tarifa_records(registros, FonteDado.CSV)
    assert len(resultados) == 2
    assert resultados[0].inicio_vigencia == date(2025, 7, 4)


def test_parse_tarifa_duplicata_ignorada() -> None:
    """Mesma vigência+posto duplicada não cria segundo posto."""
    registros = [_registro_tarifa(1, "", "472,42", "316,96")]
    registros.append(_registro_tarifa(2, "", "472,42", "316,96"))
    resultados = parse_tarifa_records(registros, FonteDado.CSV)
    assert len(resultados) == 1
    assert len(resultados[0].postos) == 1


def test_parse_tarifa_demanda_ignorada() -> None:
    """Linhas em kW são tarifas de demanda — fora do escopo (Fase 0)."""
    registros = [_registro_tarifa(1, "", "50,00", "0", unidade="kW")]
    resultados = parse_tarifa_records(registros, FonteDado.CSV)
    assert resultados == []


def test_parse_tarifa_nominal_ignorada() -> None:
    """Tarifas nominais (SigAgenteAcessante != \"Não se aplica\") ficam de fora."""
    registros = [_registro_tarifa(1, "", "5,00", "2,00", acessante="EPDP")]
    resultados = parse_tarifa_records(registros, FonteDado.CSV)
    assert resultados == []


def test_parse_tarifa_malformada_degrada_parcial() -> None:
    """Linha sem valor usa warning e descarte individual; as boas ficam."""
    registros = [_registro_tarifa(1, "Ponta", "700,00", "500,00"), None]
    # registro não-dict é pulado; uma linha sem VlrTUSD também:
    sem_valores = _registro_tarifa(2, "Fora ponta", "", "300,00")
    registros.append(sem_valores)
    resultados = parse_tarifa_records(registros, FonteDado.CSV)  # type: ignore[arg-type]
    assert len(resultados) == 1
    assert set(resultados[0].postos) == {"Ponta"}


# ---------------------------------------------------------------------------
# parse_bandeira_records
# ---------------------------------------------------------------------------
def _registro_bandeira(competencia: str, nome: str, adicional: str) -> dict[str, str]:
    """Linha real-like do acionamento mensal (Fase 0)."""
    return {
        "DatCompetencia": competencia,
        "NomBandeiraAcionada": nome,
        "VlrAdicionalBandeira": adicional,
    }


def test_parse_bandeira_normalizada() -> None:
    """R$/MWh -> R$/kWh (÷1000) na bandeira acionada."""
    bandeira = parse_bandeira_records(
        [_registro_bandeira("2026-09-01", "Amarela", "5,00")], FonteDado.CSV
    )
    assert bandeira is not None
    assert bandeira.competencia == date(2026, 9, 1)
    assert bandeira.nome == "Amarela"
    assert bandeira.adicional_rsmwh == pytest.approx(5.0)
    assert bandeira.adicional == pytest.approx(0.005)
    assert bandeira.fonte == FonteDado.CSV
    assert bandeira.consultado_em is None


def test_parse_bandeira_primeiro_registro_valido() -> None:
    """O primeiro registro válido da lista é devolvido."""
    registros = [
        _registro_bandeira("2026-09-01", "Amarela", "5,00"),
        _registro_bandeira("2026-09-01", "Vermelha P1", "10,00"),
    ]
    bandeira = parse_bandeira_records(registros, FonteDado.CSV)
    assert bandeira is not None
    assert bandeira.nome == "Amarela"


def test_parse_bandeira_consultado_em_repassado() -> None:
    """consultado_em repassado intacto quando informado."""
    agora = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    bandeira = parse_bandeira_records(
        [_registro_bandeira("2026-09-01", "Amarela", "5,00")],
        FonteDado.CSV,
        agora,
    )
    assert bandeira is not None
    assert bandeira.consultado_em == agora


def test_parse_bandeira_vazia_nao_e_erro() -> None:
    """Sem registro do mês devolve ``None`` (coordinator tenta o anterior)."""
    assert parse_bandeira_records([], FonteDado.CSV) is None


def test_parse_bandeira_malformada_sem_valor() -> None:
    """Registro sem adicional é pulado; não derruba a consulta toda."""
    registros = [
        {},
        _registro_bandeira("2026-09-01", "Amarela", "5,00"),
    ]
    bandeira = parse_bandeira_records(registros, FonteDado.CSV)
    assert bandeira is not None
    assert bandeira.nome == "Amarela"


def test_parse_bandeira_sem_nome_descartado() -> None:
    """Registro sem nome de bandeira acionada é descartado."""
    registros = [_registro_bandeira("2026-09-01", "", "5,00")]
    assert parse_bandeira_records(registros, FonteDado.CSV) is None


def test_aneel_api_error_interface() -> None:
    """O erro é uma ``Exception`` simples de mensagem livre."""
    assert issubclass(AneelApiError, Exception)
