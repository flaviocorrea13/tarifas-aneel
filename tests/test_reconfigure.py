"""Testes do fluxo de reconfiguração do recorte tarifário.

Usam o harness do Home Assistant (``hass`` + ``MockConfigEntry``) para
exercitar o fluxo real do HA 2024.10:

* o fluxo de usuário aborta recortes já configurados (o helper correto é
  ``_abort_if_unique_id_configured``, inexistente era o ``..._mismatch``);
* ``async_step_reconfigure`` abre com os dados atuais, valida na fonte,
  atualiza unique_id/título/dados e recarrega a entry;
* trocar para um recorte que já pertence a outra entry aborta sem mudar
  nada.

A validação na ANEEL é substituída por um fake para não tocar a rede.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tarifas_aneel.api import TarifaFiltro
from custom_components.tarifas_aneel.config_flow import (
    ConfigFlow,
    _titulo_da_filtro,
)
from custom_components.tarifas_aneel.const import (
    CONF_CLASSE,
    CONF_DETALHE,
    CONF_DISTRIBUIDORA,
    CONF_MODALIDADE,
    CONF_SUBCLASSE,
    CONF_SUBGRUPO,
    DOMAIN,
)

DADOS_EMS: dict[str, Any] = {
    CONF_DISTRIBUIDORA: "EMS",
    CONF_SUBGRUPO: "B1",
    CONF_CLASSE: "Residencial",
    CONF_SUBCLASSE: "Residencial",
    CONF_MODALIDADE: "Convencional",
    CONF_DETALHE: "Não se aplica",
}


def _entry(
    *,
    entry_id: str = "entry_ems",
    dados: dict[str, Any] | None = None,
    unique_id: str = "EMS_B1_Convencional",
) -> MockConfigEntry:
    """Entry mockada com o recorte padrão dos testes."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Tarifas EMS — B1 • Convencional",
        data=dict(dados or DADOS_EMS),
        unique_id=unique_id,
        entry_id=entry_id,
    )


async def _iniciar_reconfigure(hass: Any, entry: MockConfigEntry) -> Any:
    """Abre o fluxo de reconfiguração da entry."""
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )


def _validacao(monkeypatch: pytest.MonkeyPatch, resultado: str | None) -> None:
    """Substitui a consulta à ANEEL pela resposta informada."""

    async def _async_validar(self: ConfigFlow, filtro: TarifaFiltro) -> str | None:
        return resultado

    monkeypatch.setattr(ConfigFlow, "_async_validar", _async_validar)


def _sem_reload(monkeypatch: pytest.MonkeyPatch, hass: Any) -> list[str]:
    """Captura os pedidos de reload em vez de executá-los."""
    recarregadas: list[str] = []
    monkeypatch.setattr(
        hass.config_entries,
        "async_schedule_reload",
        recarregadas.append,
    )
    return recarregadas


async def test_fluxo_usuario_aborta_recorte_duplicado(hass) -> None:
    """O fluxo de usuário usa ``_abort_if_unique_id_configured``.

    Antes da correção, ``async_step_user`` chamava
    ``_abort_if_unique_id_mismatch`` (inexistente no HA 2024.10) e
    levantava ``AttributeError`` ao enviar o formulário.
    """
    entry = _entry()
    entry.add_to_hass(hass)

    resultado = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert resultado["type"] is FlowResultType.FORM

    resultado = await hass.config_entries.flow.async_configure(
        resultado["flow_id"], user_input=dict(DADOS_EMS)
    )

    assert resultado["type"] is FlowResultType.ABORT
    assert resultado["reason"] == "already_configured"


async def test_reconfigure_abre_com_os_dados_atuais(hass) -> None:
    """O formulário de reconfiguração vem preenchido com a entry."""
    entry = _entry(dados={**DADOS_EMS, CONF_MODALIDADE: "Branca"})
    entry.add_to_hass(hass)

    resultado = await _iniciar_reconfigure(hass, entry)

    assert resultado["type"] is FlowResultType.FORM
    assert resultado["step_id"] == "reconfigure"
    assert entry.supports_reconfigure is True

    padroes = {
        marcador.schema: (
            marcador.default()
            if callable(marcador.default)
            else marcador.default
        )
        for marcador in resultado["data_schema"].schema
    }
    assert padroes[CONF_DISTRIBUIDORA] == "EMS"
    assert padroes[CONF_SUBGRUPO] == "B1"
    assert padroes[CONF_CLASSE] == "Residencial"
    assert padroes[CONF_SUBCLASSE] == "Residencial"
    assert padroes[CONF_MODALIDADE] == "Branca"
    assert padroes[CONF_DETALHE] == "Não se aplica"


async def test_reconfigure_com_dados_iniciais_mostra_formulario(
    hass, monkeypatch
) -> None:
    """Dados iniciais da entry não são tratados como submissão.

    O HA 2024.10 inicia a reconfiguração passando os dados atuais da entry
    como ``user_input`` do primeiro passo (via ``async_start_reconfigure``).
    Esse caminho é simulado aqui com ``data=entry.data`` no ``async_init``,
    que funciona tanto na versão mínima quanto na estável.
    """
    _validacao(monkeypatch, None)
    recarregadas = _sem_reload(monkeypatch, hass)

    entry = _entry()
    entry.add_to_hass(hass)

    resultado = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
        data=dict(entry.data),
    )

    assert resultado["type"] is FlowResultType.FORM
    assert resultado["step_id"] == "reconfigure"
    assert recarregadas == []

    novo = {**DADOS_EMS, CONF_MODALIDADE: "Branca"}
    resultado = await hass.config_entries.flow.async_configure(
        resultado["flow_id"], user_input=novo
    )

    assert resultado["type"] is FlowResultType.ABORT
    assert resultado["reason"] == "reconfigure_successful"
    assert entry.data == novo
    assert entry.unique_id == "EMS_B1_Branca"
    assert recarregadas == [entry.entry_id]


async def test_reconfigure_troca_recorte_atualiza_e_recarrega(
    hass, monkeypatch
) -> None:
    """Salvar um novo recorte atualiza a entry e pede reload."""
    _validacao(monkeypatch, None)
    recarregadas = _sem_reload(monkeypatch, hass)

    entry = _entry()
    entry.add_to_hass(hass)

    resultado = await _iniciar_reconfigure(hass, entry)
    assert resultado["type"] is FlowResultType.FORM

    novo = {**DADOS_EMS, CONF_MODALIDADE: "Branca"}
    resultado = await hass.config_entries.flow.async_configure(
        resultado["flow_id"], user_input=novo
    )

    assert resultado["type"] is FlowResultType.ABORT
    assert resultado["reason"] == "reconfigure_successful"
    assert entry.data == novo
    assert entry.unique_id == "EMS_B1_Branca"
    assert entry.title == _titulo_da_filtro(
        TarifaFiltro(
            distribuidora="EMS",
            subgrupo="B1",
            modalidade="Branca",
            classe="Residencial",
            subclasse="Residencial",
            detalhe="Não se aplica",
        )
    )
    assert "Branca" in entry.title
    assert recarregadas == [entry.entry_id]


async def test_reconfigure_aborta_combinacao_duplicada(
    hass, monkeypatch
) -> None:
    """Não permite reconfigurar para o recorte de outra entry."""
    _validacao(monkeypatch, None)
    recarregadas = _sem_reload(monkeypatch, hass)

    entry_a = _entry(entry_id="entry_a")
    entry_b = _entry(
        entry_id="entry_b",
        dados={**DADOS_EMS, CONF_MODALIDADE: "Branca"},
        unique_id="EMS_B1_Branca",
    )
    entry_a.add_to_hass(hass)
    entry_b.add_to_hass(hass)

    resultado = await _iniciar_reconfigure(hass, entry_a)
    resultado = await hass.config_entries.flow.async_configure(
        resultado["flow_id"],
        user_input={**DADOS_EMS, CONF_MODALIDADE: "Branca"},
    )

    assert resultado["type"] is FlowResultType.ABORT
    assert resultado["reason"] == "already_configured"
    assert entry_a.data == DADOS_EMS
    assert entry_a.unique_id == "EMS_B1_Convencional"
    assert recarregadas == []


async def test_reconfigure_mostra_erro_de_validacao_sem_alterar(
    hass, monkeypatch
) -> None:
    """Falha da validação mantém o formulário e não mexe na entry."""
    _validacao(monkeypatch, "sem_dados")
    recarregadas = _sem_reload(monkeypatch, hass)

    entry = _entry()
    entry.add_to_hass(hass)

    resultado = await _iniciar_reconfigure(hass, entry)
    resultado = await hass.config_entries.flow.async_configure(
        resultado["flow_id"],
        user_input={**DADOS_EMS, CONF_MODALIDADE: "Branca"},
    )

    assert resultado["type"] is FlowResultType.FORM
    assert resultado["step_id"] == "reconfigure"
    assert resultado["errors"] == {"base": "sem_dados"}
    assert entry.data == DADOS_EMS
    assert entry.unique_id == "EMS_B1_Convencional"
    assert recarregadas == []


def _traducoes() -> dict[str, dict[str, Any]]:
    """Carrega strings.json e as traduções pt-BR/en."""
    pasta = (
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / "tarifas_aneel"
    )
    arquivos = [
        pasta / "strings.json",
        pasta / "translations" / "pt-BR.json",
        pasta / "translations" / "en.json",
    ]
    return {
        arquivo.name: json.loads(arquivo.read_text(encoding="utf-8"))
        for arquivo in arquivos
    }


def test_traducoes_do_reconfigure() -> None:
    """Passo e motivo de aborto existem em pt-BR e en."""
    traducoes = _traducoes()

    for nome, conteudo in traducoes.items():
        passo = conteudo["config"]["step"]["reconfigure"]
        assert passo["title"], nome
        assert set(passo["data"]) == {
            CONF_DISTRIBUIDORA,
            CONF_SUBGRUPO,
            CONF_CLASSE,
            CONF_SUBCLASSE,
            CONF_MODALIDADE,
            CONF_DETALHE,
        }
        assert conteudo["config"]["abort"]["reconfigure_successful"], nome

    assert traducoes["pt-BR.json"]["config"]["step"]["reconfigure"]["title"] == (
        "Reconfigurar recorte tarifário"
    )
    assert traducoes["en.json"]["config"]["step"]["reconfigure"]["title"] == (
        "Reconfigure tariff slice"
    )
