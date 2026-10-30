"""Testes do ciclo de leitura e do custo estimado (:mod:`...ciclo`)."""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.tarifas_aneel.ciclo import (
    LeituraCiclo,
    atualizar_leitura,
    calcular_custo_ciclo,
    delta_kwh,
    fim_ciclo,
    inicio_ciclo,
    normalizar_dia,
)


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        (None, 1),
        ("", 1),
        ("abc", 1),
        (0, 1),
        (-5, 1),
        (1, 1),
        ("10", 10),
        (28, 28),
        (29, 28),
        (31, 28),
    ],
)
def test_normalizar_dia(entrada: object, esperado: int) -> None:
    """Dia de leitura fica sempre em 1..28 (inválido cai no padrão)."""
    assert normalizar_dia(entrada) == esperado


@pytest.mark.parametrize(
    ("hoje", "dia", "esperado"),
    [
        (date(2026, 10, 29), 10, date(2026, 10, 10)),
        (date(2026, 10, 10), 10, date(2026, 10, 10)),  # fronteira
        (date(2026, 10, 9), 10, date(2026, 9, 10)),
        (date(2026, 1, 5), 10, date(2025, 12, 10)),  # cruza o ano
        (date(2026, 3, 1), 28, date(2026, 2, 28)),
        (date(2026, 10, 29), 1, date(2026, 10, 1)),
        (date(2026, 10, 29), None, date(2026, 10, 1)),  # ausente = dia 1
    ],
)
def test_inicio_ciclo(hoje: date, dia: object, esperado: date) -> None:
    """O ciclo que contém a data começa no dia de leitura."""
    assert inicio_ciclo(hoje, dia) == esperado


@pytest.mark.parametrize(
    ("inicio", "dia", "esperado"),
    [
        (date(2026, 10, 10), 10, date(2026, 11, 10)),
        (date(2026, 12, 10), 10, date(2027, 1, 10)),
        (date(2026, 1, 28), 28, date(2026, 2, 28)),
    ],
)
def test_fim_ciclo(inicio: date, dia: int, esperado: date) -> None:
    """O fim é o início do ciclo seguinte (fim exclusivo)."""
    assert fim_ciclo(inicio, dia) == esperado


def test_primeira_leitura_nao_conta_consumo_passado() -> None:
    """Sem baseline anterior, a contagem começa no valor atual."""
    inicio = date(2026, 10, 10)
    leitura = atualizar_leitura(None, 1000.0, inicio)
    assert leitura.baseline == 1000.0
    assert leitura.ultimo == 1000.0
    assert delta_kwh(leitura, inicio) == 0.0


def test_consumo_do_ciclo_e_a_variacao() -> None:
    """A variação do totalizador dentro do ciclo é o consumo."""
    inicio = date(2026, 10, 10)
    leitura = atualizar_leitura(None, 1000.0, inicio)
    leitura = atualizar_leitura(leitura, 1012.5, inicio)
    assert leitura.baseline == 1000.0
    assert delta_kwh(leitura, inicio) == pytest.approx(12.5)


def test_rotacao_de_ciclo_usa_ultima_leitura_como_baseline() -> None:
    """Na virada, a última leitura do ciclo anterior vira a baseline."""
    anterior = LeituraCiclo(
        inicio=date(2026, 10, 10), baseline=1000.0, ultimo=1120.0
    )
    novo = atualizar_leitura(anterior, 1125.0, date(2026, 11, 10))
    assert novo.inicio == date(2026, 11, 10)
    assert novo.baseline == 1120.0
    assert novo.ultimo == 1125.0
    assert novo.reset is False
    assert delta_kwh(novo, date(2026, 11, 10)) == pytest.approx(5.0)
    # A leitura do ciclo antigo não conta mais.
    assert delta_kwh(novo, date(2026, 10, 10)) == 0.0


def test_reset_na_virada_de_ciclo_zera_a_baseline() -> None:
    """Medidor trocado/zerado na virada do ciclo não gera delta negativo."""
    anterior = LeituraCiclo(
        inicio=date(2026, 10, 10), baseline=1000.0, ultimo=1120.0
    )
    novo = atualizar_leitura(anterior, 2.0, date(2026, 11, 10))
    assert novo.baseline == 0.0
    assert novo.reset is True
    assert delta_kwh(novo, date(2026, 11, 10)) == pytest.approx(2.0)


def test_reset_do_sensor_zera_a_baseline() -> None:
    """Se o medidor volta, a contagem recomeça do zero (reset detectado)."""
    inicio = date(2026, 10, 10)
    leitura = atualizar_leitura(None, 1000.0, inicio)
    leitura = atualizar_leitura(leitura, 1050.0, inicio)
    leitura = atualizar_leitura(leitura, 3.0, inicio)
    assert leitura.reset is True
    assert leitura.baseline == 0.0
    assert leitura.ultimo == 3.0
    assert delta_kwh(leitura, inicio) == pytest.approx(3.0)


def test_reset_continua_marcado_apos_novas_leituras() -> None:
    """O flag de reset permanece no ciclo depois de novas leituras."""
    inicio = date(2026, 10, 10)
    leitura = atualizar_leitura(None, 100.0, inicio)
    leitura = atualizar_leitura(leitura, 1.0, inicio)
    leitura = atualizar_leitura(leitura, 5.0, inicio)
    assert leitura.reset is True
    assert leitura.baseline == 0.0
    assert delta_kwh(leitura, inicio) == pytest.approx(5.0)


def test_leitura_serializa_e_recompoe() -> None:
    """Roundtrip do Store (JSON) sem perdas."""
    leitura = LeituraCiclo(
        inicio=date(2026, 10, 10), baseline=10.5, ultimo=20.0, reset=True
    )
    assert LeituraCiclo.from_dict(leitura.to_dict()) == leitura


def test_leitura_corrompida_levanta() -> None:
    """Payload inválido do Store levanta ``ValueError`` (tratado no sensor)."""
    with pytest.raises(ValueError):
        LeituraCiclo.from_dict({"inicio": "nao-e-data"})


def test_custo_do_ciclo_com_consumo_liquido() -> None:
    """(consumo - injeção) x tarifa + CIP/COSIP, arredondado em centavos."""
    assert calcular_custo_ciclo(100.0, 0.0, 1.309834, 10.0) == pytest.approx(
        140.98
    )
    assert calcular_custo_ciclo(100.0, 30.0, 1.309834, 10.0) == pytest.approx(
        101.69
    )


def test_injecao_maior_que_consumo_nao_gera_credito() -> None:
    """Crédito do próprio ciclo não vira saldo: o líquido para em zero."""
    assert calcular_custo_ciclo(10.0, 25.0, 1.0, 7.0) == pytest.approx(7.0)
