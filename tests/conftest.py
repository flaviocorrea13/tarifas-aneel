"""Configuração local dos testes com o harness do Home Assistant.

O plugin ``pytest-homeassistant-custom-component`` bloqueia sockets em
todos os testes. No Windows, o event loop do HA (Proactor) cria um
``socketpair`` via AF_INET, o que dispara ``SocketBlockedError``. Em
Linux/CI o bloqueio continua valendo; no Windows ele é desativado apenas
para permitir o event loop de teste.
"""

from __future__ import annotations

import sys

import pytest
import pytest_socket

if sys.platform == "win32":
    # O plugin chama ``disable_socket()`` antes de cada teste; no Windows
    # isso também impede o event loop de criar o self-pipe.
    pytest_socket.disable_socket = lambda *args, **kwargs: None


@pytest.fixture(autouse=True)
def _habilitar_custom_integrations(enable_custom_integrations):
    """Permite carregar ``custom_components`` nos testes do harness."""
    yield
