"""Cálculos puros de tarifa da integração Tarifas ANEEL.

Funções sem dependência do Home Assistant (nem de rede), facilitando testes
unitários com valores numéricos conhecidos.

Modelo de cálculo (valores em R$/kWh):

* ``tarifa_sem_impostos`` = TUSD + TE
* ``tarifa_com_bandeira`` = tarifa_sem_impostos + adicional da bandeira
* ``tarifa_com_impostos`` = gross-up "por dentro" da tarifa_sem_impostos
* ``tarifa_final``        = gross-up "por dentro" da tarifa_com_bandeira

Gross-up "por dentro" (como o imposto aparece na fatura brasileira): o preço
final já embute o imposto, então ``preco_final = preco_sem_impostos /
(1 - (ICMS + PIS + COFINS))``, com alíquotas em fração (ex.: 18% = 0.18).
"""

from __future__ import annotations

from custom_components.tarifas_aneel.const import RSMWH_PARA_RSKWH
from custom_components.tarifas_aneel.models import ResultadoCalculo


def rsmwh_para_rskwh(valor_rsmwh: float) -> float:
    """Converte um valor de R$/MWh (unidade publicada pela ANEEL) para R$/kWh."""
    return valor_rsmwh / RSMWH_PARA_RSKWH


def validar_aliquotas(icms: float, pis: float, cofins: float) -> float:
    """Valida as alíquotas (em fração: 0.18 = 18%) e devolve a soma.

    Levanta ``ValueError`` se alguma alíquota for negativa ou se a soma
    for >= 1 (o que equivaleria a dividir por zero ou por número negativo
    no gross-up).
    """
    if icms < 0 or pis < 0 or cofins < 0:
        msg = (
            "alíquotas não podem ser negativas "
            f"(icms={icms}, pis={pis}, cofins={cofins})"
        )
        raise ValueError(msg)
    soma = icms + pis + cofins
    if soma >= 1:
        msg = f"soma das alíquotas deve ser < 1 (recebido {soma:.4f})"
        raise ValueError(msg)
    return soma


def aplicar_impostos(
    preco_sem_impostos: float,
    icms: float,
    pis: float,
    cofins: float,
) -> float:
    """Aplica o gross-up "por dentro" de ICMS + PIS + COFINS.

    ``preco_sem_impostos`` e o retorno estão em R$/kWh. Alíquotas em fração
    (ex.: 0.18 para 18%). Levanta ``ValueError`` para preço negativo ou
    alíquotas inválidas (incluindo o caso soma == 1, que causaria divisão
    por zero).
    """
    if preco_sem_impostos < 0:
        msg = f"preço sem impostos não pode ser negativo ({preco_sem_impostos})"
        raise ValueError(msg)
    soma = validar_aliquotas(icms, pis, cofins)
    divisor = 1.0 - soma
    if divisor <= 0:  # defesa extra: inalcançável com a validação acima
        msg = f"divisor de gross-up inválido ({divisor})"
        raise ValueError(msg)
    return preco_sem_impostos / divisor


def calcular_tarifa(
    tusd: float,
    te: float,
    adicional_bandeira: float,
    icms: float = 0.0,
    pis: float = 0.0,
    cofins: float = 0.0,
) -> ResultadoCalculo:
    """Calcula a tarifa final completa, todos os valores em R$/kWh.

    ``tusd``, ``te`` e ``adicional_bandeira`` já devem estar normalizados
    em R$/kWh (use ``rsmwh_para_rskwh`` sobre os valores da ANEEL).
    Alíquotas em fração (0.18 = 18%).

    Levanta ``ValueError`` para valores negativos ou alíquotas inválidas.
    """
    if tusd < 0:
        msg = f"TUSD não pode ser negativa ({tusd})"
        raise ValueError(msg)
    if te < 0:
        msg = f"TE não pode ser negativa ({te})"
        raise ValueError(msg)
    if adicional_bandeira < 0:
        msg = f"adicional de bandeira não pode ser negativo ({adicional_bandeira})"
        raise ValueError(msg)

    tarifa_sem_impostos = tusd + te
    tarifa_com_bandeira = tarifa_sem_impostos + adicional_bandeira
    tarifa_com_impostos = aplicar_impostos(tarifa_sem_impostos, icms, pis, cofins)
    tarifa_final = aplicar_impostos(tarifa_com_bandeira, icms, pis, cofins)

    return ResultadoCalculo(
        tarifa_te=te,
        tarifa_tusd=tusd,
        tarifa_sem_impostos=tarifa_sem_impostos,
        adicional_bandeira=adicional_bandeira,
        tarifa_com_bandeira=tarifa_com_bandeira,
        tarifa_com_impostos=tarifa_com_impostos,
        tarifa_final=tarifa_final,
    )
