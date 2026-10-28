"""Modelos de dados da integração Tarifas ANEEL.

Modelos puros (sem dependências do Home Assistant), usados pelo cliente de
API, pelo coordinator, pelas entidades e pelos testes.

Todas as tarifas (TUSD, TE) e o adicional de bandeira são normalizados em
R$/kWh. Os valores originais da ANEEL são publicados em R$/MWh e a
normalização (divisão por 1000) é feita no cliente de API (``api.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any


class FonteDado(StrEnum):
    """Camada de onde o dado foi obtido (ordem de fallback do coordinator)."""

    API = "API"
    CSV = "CSV"
    CACHE = "Cache"


@dataclass(frozen=True, slots=True)
class PostoTarifa:
    """Tarifas TUSD e TE de um posto tarifário, em R$/kWh."""

    posto: str
    tusd: float
    te: float


@dataclass(frozen=True, slots=True)
class TarifaData:
    """Tarifas vigentes de uma distribuidora, normalizadas em R$/kWh.

    Na modalidade Convencional ``postos`` tem a chave "Não se aplica".
    Na modalidade Branca tem "Ponta", "Intermediário" e "Fora ponta".
    """

    distribuidora: str
    subgrupo: str
    modalidade: str
    inicio_vigencia: date
    fim_vigencia: date | None
    postos: dict[str, PostoTarifa]
    fonte: FonteDado
    classe: str | None = None
    subclasse: str | None = None
    detalhe: str | None = None
    cnpj: str | None = None
    reh: str | None = None
    gerado_em: date | None = None
    consultado_em: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serializa o modelo para persistência no Store do coordinator."""
        return {
            "distribuidora": self.distribuidora,
            "subgrupo": self.subgrupo,
            "modalidade": self.modalidade,
            "classe": self.classe,
            "subclasse": self.subclasse,
            "detalhe": self.detalhe,
            "cnpj": self.cnpj,
            "reh": self.reh,
            "inicio_vigencia": self.inicio_vigencia.isoformat(),
            "fim_vigencia": (
                self.fim_vigencia.isoformat() if self.fim_vigencia else None
            ),
            "gerado_em": self.gerado_em.isoformat() if self.gerado_em else None,
            "consultado_em": (
                self.consultado_em.isoformat() if self.consultado_em else None
            ),
            "fonte": str(self.fonte),
            "postos": {
                posto: {"posto": item.posto, "tusd": item.tusd, "te": item.te}
                for posto, item in self.postos.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TarifaData:
        """Reconstrói o modelo a partir do dicionário serializado."""
        return cls(
            distribuidora=data["distribuidora"],
            subgrupo=data["subgrupo"],
            modalidade=data["modalidade"],
            classe=data.get("classe"),
            subclasse=data.get("subclasse"),
            detalhe=data.get("detalhe"),
            cnpj=data.get("cnpj"),
            reh=data.get("reh"),
            inicio_vigencia=date.fromisoformat(data["inicio_vigencia"]),
            fim_vigencia=(
                date.fromisoformat(data["fim_vigencia"])
                if data.get("fim_vigencia")
                else None
            ),
            gerado_em=(
                date.fromisoformat(data["gerado_em"])
                if data.get("gerado_em")
                else None
            ),
            consultado_em=(
                datetime.fromisoformat(data["consultado_em"])
                if data.get("consultado_em")
                else None
            ),
            fonte=FonteDado(data["fonte"]),
            postos={
                posto: PostoTarifa(**valores)
                for posto, valores in data["postos"].items()
            },
        )


@dataclass(frozen=True, slots=True)
class BandeiraData:
    """Bandeira tarifária de um mês de competência.

    ``adicional_rsmwh`` é o valor publicado pela ANEEL em R$/MWh;
    ``adicional`` já está normalizado em R$/kWh para os cálculos.
    """

    competencia: date
    nome: str
    adicional_rsmwh: float
    adicional: float
    fonte: FonteDado
    consultado_em: datetime | None = None
    # True quando o registro do mês corrente não existe e o coordinator
    # usou o mês anterior como fallback.
    mes_anterior: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serializa o modelo para persistência no Store do coordinator."""
        return {
            "competencia": self.competencia.isoformat(),
            "nome": self.nome,
            "adicional_rsmwh": self.adicional_rsmwh,
            "adicional": self.adicional,
            "fonte": str(self.fonte),
            "consultado_em": (
                self.consultado_em.isoformat() if self.consultado_em else None
            ),
            "mes_anterior": self.mes_anterior,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BandeiraData:
        """Reconstrói o modelo a partir do dicionário serializado."""
        return cls(
            competencia=date.fromisoformat(data["competencia"]),
            nome=data["nome"],
            adicional_rsmwh=float(data["adicional_rsmwh"]),
            adicional=float(data["adicional"]),
            fonte=FonteDado(data["fonte"]),
            consultado_em=(
                datetime.fromisoformat(data["consultado_em"])
                if data.get("consultado_em")
                else None
            ),
            mes_anterior=bool(data.get("mes_anterior", False)),
        )


@dataclass(frozen=True, slots=True)
class ResultadoCalculo:
    """Resultado do cálculo da tarifa final, todos os valores em R$/kWh.

    Produzido por ``calc.py`` (funções puras):

    * ``tarifa_sem_impostos`` = TUSD + TE
    * ``tarifa_com_bandeira`` = TUSD + TE + adicional da bandeira
    * ``tarifa_com_impostos`` = (TUSD + TE) com gross-up "por dentro"
    * ``tarifa_final`` = tarifa com bandeira e impostos
    """

    tarifa_te: float
    tarifa_tusd: float
    tarifa_sem_impostos: float
    adicional_bandeira: float
    tarifa_com_bandeira: float
    tarifa_com_impostos: float
    tarifa_final: float
