"""Cliente das APIs de dados abertos da ANEEL (CKAN).

Duas camadas independentes de consulta, usadas em cascata pelo coordinator:

1. **Camada 1 — JSON oficial**: ``GET /api/3/action/datastore_search``
   (padrão CKAN), com filtros server-side e paginação;
2. **Camada 2 — CSV de dados abertos**: ``GET /datastore/dump/<resource_id>``
   com os mesmos filtros (verificado na Fase 0: o dump aceita ``filters``).

Os parsers são funções puras, testáveis sem rede. Observações da Fase 0:

* valores monetários chegam como texto com vírgula decimal ("472,42",
  ",00" para zero) — ver :func:`parse_valor_br`;
* a unidade publicada é R$/MWh para tarifas de energia (``DscUnidadeTerciaria
  == "MWh"``); linhas em "kW" são tarifas de demanda e são ignoradas;
* o adicional de bandeira é publicado em R$/MWh e normalizado para R$/kWh.

Falhas de rede/HTTP/formato levantam :class:`AneelApiError` para que o
coordinator avance para a próxima camada. "Nenhum registro" não é erro:
tarifa devolve lista vazia e bandeira devolve ``None``.
"""

from __future__ import annotations

from collections.abc import Iterable
import csv
from dataclasses import dataclass
from datetime import UTC, date, datetime
from io import StringIO
import json
import logging
from typing import Any, Final

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.tarifas_aneel.calc import rsmwh_para_rskwh
from custom_components.tarifas_aneel.const import (
    API_FIELD_BANDEIRA_ADICIONAL,
    API_FIELD_BANDEIRA_COMPETENCIA,
    API_FIELD_BANDEIRA_NOME,
    API_FIELD_BASE_TARIFARIA,
    API_FIELD_CLASSE,
    API_FIELD_CNPJ,
    API_FIELD_DETALHE,
    API_FIELD_FIM_VIGENCIA,
    API_FIELD_GERADO_EM,
    API_FIELD_INICIO_VIGENCIA,
    API_FIELD_MODALIDADE,
    API_FIELD_POSTO,
    API_FIELD_REH,
    API_FIELD_SIG_AGENTE,
    API_FIELD_SIG_AGENTE_ACESSANTE,
    API_FIELD_SUBCLASSE,
    API_FIELD_SUBGRUPO,
    API_FIELD_TE,
    API_FIELD_TUSD,
    API_FIELD_UNIDADE,
    BASE_TARIFARIA_APLICACAO,
    DATASTORE_DUMP_URL,
    DATASTORE_SEARCH_URL,
    DEFAULT_DETALHE,
    NAO_SE_APLICA,
    REQUEST_TIMEOUT,
    RESOURCE_BANDEIRA_ACIONAMENTO,
    RESOURCE_TARIFAS,
    UNIDADE_MWH,
)
from custom_components.tarifas_aneel.models import (
    BandeiraData,
    FonteDado,
    PostoTarifa,
    TarifaData,
)

_LOGGER: Final = logging.getLogger(__name__)

TARIFA_PAGE_SIZE: Final = 500
TARIFA_MAX_RECORDS: Final = 5000


class AneelApiError(Exception):
    """Falha ao consultar os dados abertos da ANEEL (rede, HTTP ou formato)."""


@dataclass(frozen=True, slots=True)
class TarifaFiltro:
    """Seleção de tarifa para consulta (espelha os filtros da Fase 0)."""

    distribuidora: str
    subgrupo: str
    modalidade: str
    classe: str
    subclasse: str
    detalhe: str = DEFAULT_DETALHE

    def to_filters(self) -> dict[str, str]:
        """Traduz o filtro para o parâmetro ``filters`` do datastore_search."""
        return {
            API_FIELD_SIG_AGENTE: self.distribuidora,
            API_FIELD_BASE_TARIFARIA: BASE_TARIFARIA_APLICACAO,
            API_FIELD_SUBGRUPO: self.subgrupo,
            API_FIELD_MODALIDADE: self.modalidade,
            API_FIELD_CLASSE: self.classe,
            API_FIELD_SUBCLASSE: self.subclasse,
            API_FIELD_DETALHE: self.detalhe,
            API_FIELD_SIG_AGENTE_ACESSANTE: NAO_SE_APLICA,
        }


# ---------------------------------------------------------------------------
# Parsers (funções puras)
# ---------------------------------------------------------------------------
def parse_valor_br(texto: str | None) -> float:
    """Converte valor monetário brasileiro em ``float``.

    Aceita o formato do dataset (vírgula decimal, ex. ``"472,42"``,
    ``",00"``) e é tolerante a ``"R$"`` e espaços. Sem vírgula, um ponto é
    tratado como separador de milhar quando o padrão é claramente
    ``999.999.999`` (ex. ``"1.234"`` -> 1234) e como decimal caso contrário
    (ex. ``"37.21"`` -> 37.21). Levanta ``ValueError`` para vazio/ausente.
    """
    if texto is None:
        raise ValueError("valor monetário ausente")
    bruto = str(texto).strip().replace("R$", "").replace(" ", "").strip()
    if not bruto:
        raise ValueError("valor monetário vazio")
    negativo = bruto.startswith("-")
    bruto = bruto.lstrip("+-")
    if "," in bruto:
        bruto = bruto.replace(".", "").replace(",", ".")
    elif "." in bruto:
        partes = bruto.split(".")
        eh_milhar = len(partes) > 1 and all(
            len(parte) == 3 for parte in partes[1:]
        )
        if eh_milhar:
            bruto = bruto.replace(".", "")
    valor = float(bruto)
    return -valor if negativo else valor


def parse_data_iso(texto: str | None) -> date:
    """Converte uma data ISO ``YYYY-MM-DD`` em :class:`datetime.date`.

    Levanta ``ValueError`` se a data estiver ausente ou malformada.
    """
    if texto is None or not str(texto).strip():
        raise ValueError("data ausente")
    try:
        return date.fromisoformat(str(texto).strip())
    except ValueError as err:
        msg = f"data inválida: {texto!r}"
        raise ValueError(msg) from err


def _data_segura(texto: str | None) -> date | None:
    """Tenta converter uma data opcional; falha silenciosa devolve None."""
    try:
        return parse_data_iso(texto)
    except ValueError:
        return None


def parse_tarifa_records(
    registros: Iterable[dict[str, Any]],
    fonte: FonteDado,
    consultado_em: datetime | None = None,
) -> list[TarifaData]:
    """Converte registros do datastore em :class:`TarifaData`.

    Regras (Fase 0):

    * ignora linhas de demanda (``DscUnidadeTerciaria == "kW"``) — a
      integração trata somente tarifas de energia (MWh);
    * ignora tarifas nominais (``SigAgenteAcessante != "Não se aplica"``);
    * agrupa linhas por vigência (início/fim) e monta o dicionário de
      postos (Chave "Não se aplica" na Convencional; "Ponta",
      "Intermediário" e "Fora ponta" na Branca);
    * deduplica linhas repetidas do dataset (registro duplicado é comum);
    * o resultado é ordenado por vigência mais recente primeiro, para que o
      fallback "vigente inexistente -> mais recente" seja ``[0]``.

    Linhas malformadas são registradas em ``warning`` e descartadas
    individualmente (degradação parcial em vez de falha total).
    """
    por_vigencia: dict[
        tuple[date, date | None], dict[str, Any]
    ] = {}
    for linha in registros:
        if not isinstance(linha, dict):
            continue
        unidade = str(linha.get(API_FIELD_UNIDADE) or "").strip()
        if unidade != UNIDADE_MWH:
            _LOGGER.debug(
                "Registro de tarifa ignorado (unidade %r, _id=%r)",
                unidade,
                linha.get("_id"),
            )
            continue
        acessante = str(linha.get(API_FIELD_SIG_AGENTE_ACESSANTE) or "").strip()
        if acessante not in ("", NAO_SE_APLICA):
            _LOGGER.debug(
                "Tarifa nominal ignorada (acessante %r, _id=%r)",
                acessante,
                linha.get("_id"),
            )
            continue
        try:
            tusd = parse_valor_br(linha.get(API_FIELD_TUSD))
            te = parse_valor_br(linha.get(API_FIELD_TE))
            inicio = parse_data_iso(linha.get(API_FIELD_INICIO_VIGENCIA))
        except ValueError as err:
            _LOGGER.warning(
                "Registro de tarifa malformado ignorado (%s) — degradação parcial",
                err,
            )
            continue
        fim: date | None = None
        fim_bruto = str(linha.get(API_FIELD_FIM_VIGENCIA) or "").strip()
        if fim_bruto:
            try:
                fim = parse_data_iso(fim_bruto)
            except ValueError as err:
                _LOGGER.warning(
                    "DatFimVigencia inválida (%s) — vigência tratada como aberta",
                    err,
                )
        posto = str(linha.get(API_FIELD_POSTO) or "").strip() or NAO_SE_APLICA
        chave = (inicio, fim)
        grupo = por_vigencia.setdefault(chave, {"postos": {}, "amostra": linha})
        if posto in grupo["postos"]:
            _LOGGER.debug(
                "Linha duplicada ignorada (vigência %s, posto %r)",
                chave,
                posto,
            )
            continue
        grupo["postos"][posto] = PostoTarifa(
            posto=posto,
            tusd=rsmwh_para_rskwh(tusd),
            te=rsmwh_para_rskwh(te),
        )

    resultados: list[TarifaData] = []
    for (inicio, fim), grupo in por_vigencia.items():
        amostra: dict[str, Any] = grupo["amostra"]
        resultados.append(
            TarifaData(
                distribuidora=str(amostra.get(API_FIELD_SIG_AGENTE) or "").strip(),
                subgrupo=str(amostra.get(API_FIELD_SUBGRUPO) or "").strip(),
                modalidade=str(amostra.get(API_FIELD_MODALIDADE) or "").strip(),
                classe=str(amostra.get(API_FIELD_CLASSE) or "").strip() or None,
                subclasse=str(amostra.get(API_FIELD_SUBCLASSE) or "").strip()
                or None,
                detalhe=str(amostra.get(API_FIELD_DETALHE) or "").strip() or None,
                cnpj=str(amostra.get(API_FIELD_CNPJ) or "").strip() or None,
                reh=str(amostra.get(API_FIELD_REH) or "").strip() or None,
                gerado_em=_data_segura(amostra.get(API_FIELD_GERADO_EM)),
                inicio_vigencia=inicio,
                fim_vigencia=fim,
                postos=dict(grupo["postos"]),
                fonte=fonte,
                consultado_em=consultado_em,
            )
        )
    resultados.sort(key=lambda tarifa: tarifa.inicio_vigencia, reverse=True)
    return resultados


def parse_bandeira_records(
    registros: Iterable[dict[str, Any]],
    fonte: FonteDado,
    consultado_em: datetime | None = None,
) -> BandeiraData | None:
    """Converte registros do acionamento mensal em :class:`BandeiraData`.

    O filtro já garante um único mês; devolve o primeiro registro válido ou
    ``None`` quando não há dado (não é erro — o coordinator pode tentar o
    mês anterior). Valores chegam em R$/MWh e são normalizados para R$/kWh.
    """
    for linha in registros:
        if not isinstance(linha, dict):
            continue
        try:
            competencia = parse_data_iso(
                linha.get(API_FIELD_BANDEIRA_COMPETENCIA)
            )
            nome = str(linha.get(API_FIELD_BANDEIRA_NOME) or "").strip()
            adicional_rsmwh = parse_valor_br(
                linha.get(API_FIELD_BANDEIRA_ADICIONAL)
            )
        except ValueError as err:
            _LOGGER.warning(
                "Registro de bandeira malformado ignorado (%s) — degradação parcial",
                err,
            )
            continue
        if not nome:
            _LOGGER.warning("Registro de bandeira sem nome ignorado")
            continue
        return BandeiraData(
            competencia=competencia,
            nome=nome,
            adicional_rsmwh=adicional_rsmwh,
            adicional=rsmwh_para_rskwh(adicional_rsmwh),
            fonte=fonte,
            consultado_em=consultado_em,
        )
    return None


# ---------------------------------------------------------------------------
# Transporte (aiohttp)
# ---------------------------------------------------------------------------
async def _async_get_json(
    session: aiohttp.ClientSession,
    url: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Faz GET e devolve o envelope ``result`` do CKAN validando ``success``."""
    try:
        async with session.get(
            url,
            params=params,
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        ) as resp:
            resp.raise_for_status()
            dados = await resp.json(content_type=None)
    except (TimeoutError, aiohttp.ClientError, ValueError) as err:
        msg = f"falha ao consultar {url}: {err}"
        raise AneelApiError(msg) from err
    if not isinstance(dados, dict) or dados.get("success") is not True:
        resumo = str(dados)[:200]
        msg = f"resposta CKAN inesperada: {resumo}"
        raise AneelApiError(msg)
    return dados.get("result") or {}


async def _async_get_csv(
    session: aiohttp.ClientSession,
    url: str,
    params: dict[str, Any],
) -> str:
    """Faz GET de um dump CSV e devolve o texto decodificado (UTF-8/BOM)."""
    try:
        async with session.get(
            url,
            params=params,
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        ) as resp:
            resp.raise_for_status()
            bruto = await resp.read()
    except (TimeoutError, aiohttp.ClientError) as err:
        msg = f"falha ao consultar {url}: {err}"
        raise AneelApiError(msg) from err
    return bruto.decode("utf-8-sig", errors="replace")


def _registros_do_csv(texto: str) -> list[dict[str, Any]]:
    """Converte o CSV do datastore/dump em lista de dicionários."""
    leitor = csv.DictReader(StringIO(texto))
    return [dict(linha) for linha in leitor]


# ---------------------------------------------------------------------------
# Camada 1 — JSON oficial
# ---------------------------------------------------------------------------
async def async_fetch_tarifa_json(
    hass: HomeAssistant,
    filtro: TarifaFiltro,
) -> list[TarifaData]:
    """Busca tarifas via datastore_search (camada 1), paginado.

    Devolve TODAS as vigências encontradas para o filtro (a escolha da
    vigência corrente é do coordinator), ordenadas da mais recente para a
    mais antiga. Lista vazia = nenhum registro (não é erro).
    """
    session = async_get_clientsession(hass)
    consultado_em = datetime.now(tz=UTC)
    filtros_api = filtro.to_filters()
    _LOGGER.debug(
        "Camada 1 (JSON): consultando tarifas de %s (subgrupo %s, %s)",
        filtro.distribuidora,
        filtro.subgrupo,
        filtro.modalidade,
    )
    registros: list[dict[str, Any]] = []
    offset = 0
    while True:
        params: dict[str, Any] = {
            "resource_id": RESOURCE_TARIFAS,
            "limit": TARIFA_PAGE_SIZE,
            "offset": offset,
            "filters": json.dumps(filtros_api),
        }
        resultado = await _async_get_json(session, DATASTORE_SEARCH_URL, params)
        pagina = resultado.get("records") or []
        registros.extend(pagina)
        if len(pagina) < TARIFA_PAGE_SIZE or len(registros) >= TARIFA_MAX_RECORDS:
            break
        offset += TARIFA_PAGE_SIZE
    candidatos = [
        tarifa
        for tarifa in parse_tarifa_records(registros, FonteDado.API, consultado_em)
        if tarifa.distribuidora == filtro.distribuidora
    ]
    _LOGGER.debug(
        "Camada 1 (JSON): %d vigência(s) de tarifa para %s",
        len(candidatos),
        filtro.distribuidora,
    )
    return candidatos


async def async_fetch_bandeira_json(
    hass: HomeAssistant,
    competencia: date,
) -> BandeiraData | None:
    """Busca a bandeira do mês de competência via datastore_search (camada 1).

    Devolve ``None`` se não houver registro do mês (o coordinator deve
    tentar o mês anterior). O valor é normalizado de R$/MWh para R$/kWh.
    """
    session = async_get_clientsession(hass)
    filtros = {API_FIELD_BANDEIRA_COMPETENCIA: competencia.isoformat()}
    params: dict[str, Any] = {
        "resource_id": RESOURCE_BANDEIRA_ACIONAMENTO,
        "limit": 5,
        "filters": json.dumps(filtros),
    }
    _LOGGER.debug(
        "Camada 1 (JSON): consultando bandeira da competência %s",
        competencia.isoformat(),
    )
    resultado = await _async_get_json(session, DATASTORE_SEARCH_URL, params)
    bandeira = parse_bandeira_records(
        resultado.get("records") or [], FonteDado.API, datetime.now(tz=UTC)
    )
    if bandeira is None:
        _LOGGER.debug(
            "Camada 1 (JSON): sem registro de bandeira para %s",
            competencia.isoformat(),
        )
    return bandeira


# ---------------------------------------------------------------------------
# Camada 2 — CSV de dados abertos (datastore/dump aceita filters — Fase 0)
# ---------------------------------------------------------------------------
async def async_fetch_tarifa_csv(
    hass: HomeAssistant,
    filtro: TarifaFiltro,
) -> list[TarifaData]:
    """Busca tarifas via dump CSV (camada 2), com os mesmos filtros."""
    session = async_get_clientsession(hass)
    consultado_em = datetime.now(tz=UTC)
    url = f"{DATASTORE_DUMP_URL}/{RESOURCE_TARIFAS}"
    params: dict[str, Any] = {
        "filters": json.dumps(filtro.to_filters()),
        "format": "csv",
    }
    _LOGGER.debug(
        "Camada 2 (CSV): consultando tarifas de %s (subgrupo %s, %s)",
        filtro.distribuidora,
        filtro.subgrupo,
        filtro.modalidade,
    )
    texto = await _async_get_csv(session, url, params)
    candidatos = [
        tarifa
        for tarifa in parse_tarifa_records(
            _registros_do_csv(texto), FonteDado.CSV, consultado_em
        )
        if tarifa.distribuidora == filtro.distribuidora
    ]
    _LOGGER.debug(
        "Camada 2 (CSV): %d vigência(s) de tarifa para %s",
        len(candidatos),
        filtro.distribuidora,
    )
    return candidatos


async def async_fetch_bandeira_csv(
    hass: HomeAssistant,
    competencia: date,
) -> BandeiraData | None:
    """Busca a bandeira do mês via dump CSV (camada 2)."""
    session = async_get_clientsession(hass)
    url = f"{DATASTORE_DUMP_URL}/{RESOURCE_BANDEIRA_ACIONAMENTO}"
    filtros = {API_FIELD_BANDEIRA_COMPETENCIA: competencia.isoformat()}
    params: dict[str, Any] = {
        "filters": json.dumps(filtros),
        "format": "csv",
    }
    _LOGGER.debug(
        "Camada 2 (CSV): consultando bandeira da competência %s",
        competencia.isoformat(),
    )
    texto = await _async_get_csv(session, url, params)
    bandeira = parse_bandeira_records(
        _registros_do_csv(texto), FonteDado.CSV, datetime.now(tz=UTC)
    )
    if bandeira is None:
        _LOGGER.debug(
            "Camada 2 (CSV): sem registro de bandeira para %s",
            competencia.isoformat(),
        )
    return bandeira
