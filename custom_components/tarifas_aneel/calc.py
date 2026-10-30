"""Cálculos puros de tarifa da integração Tarifas ANEEL.

Funções sem dependência do Home Assistant (nem de rede), facilitando testes
unitários com valores numéricos conhecidos.

Modelo de cálculo (valores em R$/kWh):

* ``tarifa_sem_impostos`` = TUSD + TE
* ``tarifa_com_bandeira`` = tarifa_sem_impostos + adicional da bandeira
* ``tarifa_com_impostos`` = gross-up "por dentro" da tarifa_sem_impostos
* ``tarifa_final``        = gross-up "por dentro" da tarifa_com_bandeira

Gross-up "por dentro" (como o imposto aparece na fatura brasileira). Há dois
modelos, escolhidos pela opção ``pis_cofins_sem_icms``:

* **Padrão (recomendado)**: o PIS/COFINS incide sobre uma base sem o ICMS,
  então ``preco_final = preco_sem_impostos / ((1 - ICMS) * (1 - PIS -
  COFINS))``.
* **Alternativa (fórmula antiga)**: todos os tributos incidem sobre a mesma
  base, então ``preco_final = preco_sem_impostos / (1 - (ICMS + PIS +
  COFINS))``.

Alíquotas são frações (ex.: 18% = 0.18), nunca percentuais.
"""

from __future__ import annotations

from custom_components.tarifas_aneel.const import RSMWH_PARA_RSKWH
from custom_components.tarifas_aneel.models import ResultadoCalculo


def rsmwh_para_rskwh(valor_rsmwh: float) -> float:
    """Converte um valor de R$/MWh (unidade publicada pela ANEEL) para R$/kWh."""
    return valor_rsmwh / RSMWH_PARA_RSKWH


def validar_aliquotas(
    icms: float,
    pis: float,
    cofins: float,
    *,
    pis_cofins_sem_icms: bool = True,
) -> float:
    """Valida as alíquotas (em fração: 0.18 = 18%) e devolve o divisor.

    Regras (sempre aplicadas, qualquer que seja a fórmula):

    * ``0 <= ICMS < 1``;
    * ``0 <= PIS`` e ``0 <= COFINS``;
    * ``0 <= PIS + COFINS < 1``.

    Na fórmula antiga (``pis_cofins_sem_icms=False``) a soma
    ``ICMS + PIS + COFINS`` também precisa ser ``< 1``.

    O retorno é o divisor do gross-up (sempre > 0), pronto para dividir o
    preço sem impostos. Levanta ``ValueError`` quando alguma regra falha.
    """
    if icms < 0 or pis < 0 or cofins < 0:
        msg = (
            "alíquotas não podem ser negativas "
            f"(icms={icms}, pis={pis}, cofins={cofins})"
        )
        raise ValueError(msg)
    if icms >= 1:
        msg = f"ICMS deve ser < 1 (recebido {icms:.4f})"
        raise ValueError(msg)
    soma_pis_cofins = pis + cofins
    if soma_pis_cofins >= 1:
        msg = (
            "PIS + COFINS deve ser < 1 "
            f"(recebido {soma_pis_cofins:.4f})"
        )
        raise ValueError(msg)

    if pis_cofins_sem_icms:
        # PIS/COFINS incidem sobre a base sem ICMS (padrão da fatura).
        divisor = (1.0 - icms) * (1.0 - soma_pis_cofins)
    else:
        soma = icms + soma_pis_cofins
        if soma >= 1:
            msg = f"soma das alíquotas deve ser < 1 (recebido {soma:.4f})"
            raise ValueError(msg)
        divisor = 1.0 - soma

    if divisor <= 0:  # defesa extra: inalcançável com as validações acima
        msg = f"divisor de gross-up inválido ({divisor})"
        raise ValueError(msg)
    return divisor


def aplicar_impostos(
    preco_sem_impostos: float,
    icms: float,
    pis: float,
    cofins: float,
    *,
    pis_cofins_sem_icms: bool = True,
) -> float:
    """Aplica o gross-up "por dentro" de ICMS + PIS + COFINS.

    ``preco_sem_impostos`` e o retorno estão em R$/kWh. Alíquotas em fração
    (ex.: 0.18 para 18%). Com ``pis_cofins_sem_icms=True`` (padrão) usa
    ``preco / ((1 - ICMS) * (1 - PIS - COFINS))``; com ``False`` usa a
    fórmula antiga ``preco / (1 - (ICMS + PIS + COFINS))``.

    Levanta ``ValueError`` para preço negativo ou alíquotas inválidas.
    """
    if preco_sem_impostos < 0:
        msg = f"preço sem impostos não pode ser negativo ({preco_sem_impostos})"
        raise ValueError(msg)
    divisor = validar_aliquotas(
        icms, pis, cofins, pis_cofins_sem_icms=pis_cofins_sem_icms
    )
    return preco_sem_impostos / divisor


def calcular_tarifa(
    tusd: float,
    te: float,
    adicional_bandeira: float,
    icms: float = 0.0,
    pis: float = 0.0,
    cofins: float = 0.0,
    *,
    pis_cofins_sem_icms: bool = True,
) -> ResultadoCalculo:
    """Calcula a tarifa final completa, todos os valores em R$/kWh.

    ``tusd``, ``te`` e ``adicional_bandeira`` já devem estar normalizados
    em R$/kWh (use ``rsmwh_para_rskwh`` sobre os valores da ANEEL).
    Alíquotas em fração (0.18 = 18%). ``pis_cofins_sem_icms`` escolhe a
    fórmula do gross-up (ver :func:`aplicar_impostos`).

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
    tarifa_com_impostos = aplicar_impostos(
        tarifa_sem_impostos,
        icms,
        pis,
        cofins,
        pis_cofins_sem_icms=pis_cofins_sem_icms,
    )
    tarifa_final = aplicar_impostos(
        tarifa_com_bandeira,
        icms,
        pis,
        cofins,
        pis_cofins_sem_icms=pis_cofins_sem_icms,
    )

    return ResultadoCalculo(
        tarifa_te=te,
        tarifa_tusd=tusd,
        tarifa_sem_impostos=tarifa_sem_impostos,
        adicional_bandeira=adicional_bandeira,
        tarifa_com_bandeira=tarifa_com_bandeira,
        tarifa_com_impostos=tarifa_com_impostos,
        tarifa_final=tarifa_final,
    )
