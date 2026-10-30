"""Ciclo de leitura do medidor e custo estimado (cálculo puro).

A fatura de energia não fecha no mês calendário: cada distribuidora faz a
leitura em um dia do mês (ex.: dia 10). Este módulo isola a aritmética do
ciclo e da variação dos medidores totalizadores, sem depender do Home
Assistant, para que possa ser testada diretamente.

Convenções:

* o ciclo começa no ``dia_leitura`` (1 a 28) e termina no dia anterior ao
  próximo ``dia_leitura`` — ``fim`` é o início do ciclo seguinte;
* os medidores devem ser totalizadores (``state_class`` ``total`` ou
  ``total_increasing``): o consumo do ciclo é a diferença entre a leitura
  atual e a leitura registrada no início do ciclo;
* um medidor que "volta" (reset, troca de medidor ou rollover) tem a
  baseline zerada, e a contagem recomeça a partir do valor atual.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from custom_components.tarifas_aneel.const import (
    DEFAULT_DIA_LEITURA,
    MAX_DIA_LEITURA,
    MIN_DIA_LEITURA,
)


def normalizar_dia(valor: Any) -> int:
    """Converte o dia de leitura em inteiro dentro de 1..28.

    Valores ausentes, inválidos ou fora da faixa caem no padrão (dia 1),
    que equivale ao mês calendário.
    """
    try:
        dia = int(valor)
    except (TypeError, ValueError):
        return DEFAULT_DIA_LEITURA
    return min(max(dia, MIN_DIA_LEITURA), MAX_DIA_LEITURA)


def _mes_anterior(ano: int, mes: int) -> tuple[int, int]:
    """Ano e mês imediatamente anteriores."""
    if mes == 1:
        return ano - 1, 12
    return ano, mes - 1


def inicio_ciclo(hoje: date, dia_leitura: Any) -> date:
    """Início do ciclo de leitura que contém ``hoje``.

    Exemplos com dia 10: 29/10 -> 10/10; 05/10 -> 10/09.
    """
    dia = normalizar_dia(dia_leitura)
    if hoje.day >= dia:
        return date(hoje.year, hoje.month, dia)
    ano, mes = _mes_anterior(hoje.year, hoje.month)
    return date(ano, mes, dia)


def fim_ciclo(inicio: date, dia_leitura: Any) -> date:
    """Início do ciclo seguinte (fim exclusivo do ciclo atual)."""
    dia = normalizar_dia(dia_leitura)
    if inicio.month == 12:
        return date(inicio.year + 1, 1, dia)
    return date(inicio.year, inicio.month + 1, dia)


@dataclass(frozen=True, slots=True)
class LeituraCiclo:
    """Estado de um medidor totalizador dentro de um ciclo.

    ``baseline`` é a leitura no início do ciclo; ``ultimo`` é a última
    leitura observada (usada como baseline do próximo ciclo e para
    detectar reset); ``reset`` indica que o medidor recomeçou do zero.
    """

    inicio: date
    baseline: float
    ultimo: float
    reset: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serializa para o :class:`Store` do Home Assistant."""
        return {
            "inicio": self.inicio.isoformat(),
            "baseline": self.baseline,
            "ultimo": self.ultimo,
            "reset": self.reset,
        }

    @classmethod
    def from_dict(cls, dados: Any) -> LeituraCiclo:
        """Recompõe a leitura persistida; ``ValueError`` se corrompida."""
        if not isinstance(dados, dict):
            msg = "leitura de ciclo inválida"
            raise ValueError(msg)
        return cls(
            inicio=date.fromisoformat(str(dados["inicio"])),
            baseline=float(dados["baseline"]),
            ultimo=float(dados["ultimo"]),
            reset=bool(dados.get("reset", False)),
        )


def atualizar_leitura(
    anterior: LeituraCiclo | None,
    atual: float,
    inicio: date,
) -> LeituraCiclo:
    """Atualiza a leitura do medidor para o ciclo ``inicio``.

    * primeira leitura: a baseline é o próprio valor atual (a contagem
      começa na configuração);
    * ciclo novo: a baseline é a última leitura do ciclo anterior, a melhor
      aproximação do valor no instante da virada;
    * valor menor que a última leitura: reset/rollover — a baseline zera e
      a contagem recomeça do valor atual.
    """
    if anterior is None:
        return LeituraCiclo(inicio=inicio, baseline=atual, ultimo=atual)
    if anterior.inicio != inicio:
        # Virada de ciclo com o medidor "voltando" (troca de medidor ou
        # rollover): a leitura anterior não serve de baseline.
        if atual < anterior.ultimo:
            return LeituraCiclo(
                inicio=inicio,
                baseline=0.0,
                ultimo=atual,
                reset=True,
            )
        return LeituraCiclo(
            inicio=inicio,
            baseline=anterior.ultimo,
            ultimo=atual,
        )
    if atual < anterior.ultimo:
        return LeituraCiclo(
            inicio=inicio,
            baseline=0.0,
            ultimo=atual,
            reset=True,
        )
    return LeituraCiclo(
        inicio=inicio,
        baseline=anterior.baseline,
        ultimo=atual,
        reset=anterior.reset,
    )


def delta_kwh(leitura: LeituraCiclo | None, inicio: date) -> float:
    """Energia acumulada no ciclo (0 se a leitura não é do ciclo atual)."""
    if leitura is None or leitura.inicio != inicio:
        return 0.0
    return max(leitura.ultimo - leitura.baseline, 0.0)


def calcular_custo_ciclo(
    consumo_kwh: float,
    injecao_kwh: float,
    tarifa_final: float,
    cip_cosip: float,
) -> float:
    """Custo estimado do ciclo: consumo líquido x tarifa + CIP/COSIP.

    ``consumo_liquido = max(consumo - injecao, 0)`` — a injeção só abate o
    consumo do próprio ciclo. Créditos acumulados de ciclos anteriores
    (saldo de GD) **não** são considerados.
    """
    liquido = max(consumo_kwh - injecao_kwh, 0.0)
    return round(liquido * tarifa_final + cip_cosip, 2)
