"""Testes de sanidade das constantes (:mod:`custom_components.tarifas_aneel.const`).

Contratos que a integração inteira depende — quebrar qualquer um destes
valores derruba as consultas ao dataset (ex.: grafias de filtro).
"""

from __future__ import annotations

from custom_components.tarifas_aneel.const import (
    BASE_TARIFARIA_APLICACAO,
    DISTRIBUTORS,
    DOMAIN,
    MODALIDADES_GRUPO_B,
    NAO_SE_APLICA,
    RESOURCE_TARIFAS,
    RSMWH_PARA_RSKWH,
    SUBCLASSES,
    SUBGRUPOS,
)


def test_valores_canonicos() -> None:
    """Constantes de domínio e conversão."""
    assert DOMAIN == "tarifas_aneel"
    # 1 MWh = 1000 kWh:
    assert RSMWH_PARA_RSKWH == 1000.0
    assert BASE_TARIFARIA_APLICACAO == "Tarifa de Aplicação"


def test_seletores_conhecidos() -> None:
    """Seletor de subgrupo contempla o B1 residencial."""
    assert "B1" in SUBGRUPOS
    assert NAO_SE_APLICA in SUBCLASSES  # en-dash preservado nos rótulos


def test_distribuidoras_unicas() -> None:
    """Sem siglas duplicadas no dropdown (quebraria already_configured)."""
    assert len(DISTRIBUTORS) == len(set(DISTRIBUTORS))
    assert len(DISTRIBUTORS) >= 100  # 114 na base original


def test_modalidades_grupo_b() -> None:
    """Duas modalidades, canônicas e sem grafia alternativa."""
    assert MODALIDADES_GRUPO_B == ("Convencional", "Branca")


def test_resource_tarifas_preenchido() -> None:
    """O resource_id de tarifas é um UUID válido da base da ANEEL."""
    import uuid

    uuid.UUID(RESOURCE_TARIFAS)
