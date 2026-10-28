"""Smoke test de import: cada módulo da integração carrega sem erro.

Pega falhas de símbolo (nome indefinido, import órfão) que a compilação
isolada não detecta.
"""

from __future__ import annotations

import importlib

MODULOS: tuple[str, ...] = (
    "api",
    "binary_sensor",
    "button",
    "calc",
    "const",
    "diagnostics",
    "entity",
    "sensor",
)


def test_importa_todos_os_modulos() -> None:
    """Cada módulo importa sem exceção."""
    for nome in MODULOS:
        assert importlib.import_module(f"custom_components.tarifas_aneel.{nome}")
