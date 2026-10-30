"""Constantes da integração Tarifas ANEEL.

Endereços, resource IDs, nomes de campos e valores de filtro foram
verificados diretamente na API do Portal de Dados Abertos da ANEEL (CKAN)
em outubro/2026 (Fase 0). Não altere um resource_id sem revalidar na fonte:
https://dadosabertos.aneel.gov.br
"""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "tarifas_aneel"

# ---------------------------------------------------------------------------
# Endpoints oficiais (CKAN - Portal de Dados Abertos da ANEEL)
# ---------------------------------------------------------------------------
ANEEL_BASE_URL: Final = "https://dadosabertos.aneel.gov.br"
DATASTORE_SEARCH_URL: Final = f"{ANEEL_BASE_URL}/api/3/action/datastore_search"
DATASTORE_DUMP_URL: Final = f"{ANEEL_BASE_URL}/datastore/dump"
DATASET_TARIFAS_URL: Final = (
    f"{ANEEL_BASE_URL}/dataset/tarifas-distribuidoras-energia-eletrica"
)
DATASET_BANDEIRAS_URL: Final = f"{ANEEL_BASE_URL}/dataset/bandeiras-tarifarias"

# Resource IDs (datastore active) validados na Fase 0.
RESOURCE_TARIFAS: Final = "fcf2906c-7c32-4b9b-a637-054e7a5234f4"
RESOURCE_BANDEIRA_ACIONAMENTO: Final = "0591b8f6-fe54-437b-b72b-1aa2efd46e42"
RESOURCE_BANDEIRA_ADICIONAL: Final = "5879ca80-b3bd-45b1-a135-d9b77c1d5b36"

# ---------------------------------------------------------------------------
# Campos do dataset "Tarifas de aplicação das distribuidoras" (como na API)
# ---------------------------------------------------------------------------
API_FIELD_ID: Final = "_id"
API_FIELD_GERADO_EM: Final = "DatGeracaoConjuntoDados"
API_FIELD_REH: Final = "DscREH"
API_FIELD_SIG_AGENTE: Final = "SigAgente"
API_FIELD_CNPJ: Final = "NumCNPJDistribuidora"
API_FIELD_INICIO_VIGENCIA: Final = "DatInicioVigencia"
API_FIELD_FIM_VIGENCIA: Final = "DatFimVigencia"
API_FIELD_BASE_TARIFARIA: Final = "DscBaseTarifaria"
API_FIELD_SUBGRUPO: Final = "DscSubGrupo"
API_FIELD_MODALIDADE: Final = "DscModalidadeTarifaria"
API_FIELD_CLASSE: Final = "DscClasse"
API_FIELD_SUBCLASSE: Final = "DscSubClasse"
API_FIELD_DETALHE: Final = "DscDetalhe"
API_FIELD_POSTO: Final = "NomPostoTarifario"
API_FIELD_UNIDADE: Final = "DscUnidadeTerciaria"
API_FIELD_SIG_AGENTE_ACESSANTE: Final = "SigAgenteAcessante"
API_FIELD_TUSD: Final = "VlrTUSD"
API_FIELD_TE: Final = "VlrTE"

# Campos do dataset "Bandeira Tarifária - Acionamento" (como na API).
API_FIELD_BANDEIRA_COMPETENCIA: Final = "DatCompetencia"
API_FIELD_BANDEIRA_NOME: Final = "NomBandeiraAcionada"
API_FIELD_BANDEIRA_ADICIONAL: Final = "VlrAdicionalBandeira"

# ---------------------------------------------------------------------------
# Valores canônicos de filtro (validados na Fase 0, grafia exata da API)
# ---------------------------------------------------------------------------
BASE_TARIFARIA_APLICACAO: Final = "Tarifa de Aplicação"
NAO_SE_APLICA: Final = "Não se aplica"
DETALHE_SCEE: Final = "SCEE"
UNIDADE_MWH: Final = "MWh"
NAO_INFORMADO: Final = "Não Informado"

MODALIDADE_CONVENCIONAL: Final = "Convencional"
MODALIDADE_BRANCA: Final = "Branca"

# Nomes de bandeira conforme o dataset de acionamento mensal.
BANDEIRA_VERDE: Final = "Verde"
BANDEIRA_AMARELA: Final = "Amarela"
BANDEIRA_VERMELHA_P1: Final = "Vermelha P1"
BANDEIRA_VERMELHA_P2: Final = "Vermelha P2"
BANDEIRA_ESCASSEZ_HIDRICA: Final = "Escassez Hídrica"

# Postos tarifários da modalidade Branca (Grupo B).
POSTO_PONTA: Final = "Ponta"
POSTO_INTERMEDIARIO: Final = "Intermediário"
POSTO_FORA_PONTA: Final = "Fora ponta"

# ---------------------------------------------------------------------------
# Opções dos seletores (valores distintos reais levantados na Fase 0)
# ---------------------------------------------------------------------------
SUBGRUPOS: Final[tuple[str, ...]] = (
    "A1",
    "A2",
    "A3",
    "A3a",
    "A4",
    "A4a",
    "A4b",
    "AS",
    "B",
    "B1",
    "B2",
    "B3",
    "B4",
)
CLASSES: Final[tuple[str, ...]] = (
    NAO_SE_APLICA,
    "Iluminação pública",
    "Residencial",
    "Rural",
)
SUBCLASSES: Final[tuple[str, ...]] = (
    NAO_SE_APLICA,
    "Baixa Renda",
    "Cooperativa de eletrificação rural",
    "Iluminação pública – B4a",
    "Iluminação pública – B4b",
    "Residencial",
    "Residencial Desconto Social – faixa 01",
    "Residencial Desconto Social – faixa 02",
    "Residencial Tarifa Social – faixa 01",
    "Residencial Tarifa Social – faixa 02",
    "Serviço público de irrigação rural",
)
# O seletor de modalidade fica limitado às duas modalidades do Grupo B
# contempladas nesta integração (a API tem outras modalidades do Grupo A).
MODALIDADES_GRUPO_B: Final[tuple[str, ...]] = (
    MODALIDADE_CONVENCIONAL,
    MODALIDADE_BRANCA,
)

# ---------------------------------------------------------------------------
# Chaves de configuração (config entry)
# ---------------------------------------------------------------------------
CONF_DISTRIBUIDORA: Final = "distribuidora"
CONF_SUBGRUPO: Final = "subgrupo"
CONF_CLASSE: Final = "classe"
CONF_SUBCLASSE: Final = "subclasse"
CONF_MODALIDADE: Final = "modalidade"
CONF_DETALHE: Final = "detalhe"
CONF_CNPJ: Final = "cnpj"

# ---------------------------------------------------------------------------
# Chaves de opções (options flow)
# ---------------------------------------------------------------------------
OPT_ICMS: Final = "icms_percentual"
OPT_PIS: Final = "pis_percentual"
OPT_COFINS: Final = "cofins_percentual"
# True (padrão): PIS/COFINS incidem sobre a base sem ICMS.
OPT_PIS_COFINS_SEM_ICMS: Final = "pis_cofins_sem_icms"
OPT_CIP_COSIP: Final = "cip_cosip_mensal"
OPT_UPDATE_INTERVAL: Final = "update_interval_horas"
OPT_CONSUMO_ENTITY_ID: Final = "consumo_entity_id"
OPT_INJECAO_ENTITY_ID: Final = "injecao_entity_id"
# Dia do mês em que a distribuidora faz a leitura do medidor (1 a 28).
# Define o ciclo do custo estimado. Ausente = dia 1 (mês calendário).
OPT_DIA_LEITURA: Final = "dia_leitura"
# Data (ISO) em que as alíquotas foram salvas pela última vez. Usada pelo
# lembrete de revisão de impostos (repair issue não bloqueante).
OPT_ALIQUOTAS_REVISADAS_EM: Final = "aliquotas_revisadas_em"
OPT_PONTA_INICIO: Final = "ponta_inicio"
OPT_PONTA_FIM: Final = "ponta_fim"

# ---------------------------------------------------------------------------
# Padrões
# ---------------------------------------------------------------------------
# A ANEEL não publica alíquotas de ICMS/PIS/COFINS: variam por estado,
# distribuidora e mês. O padrão 0 evita "inventar" impostos; o usuário
# confere os valores reais na própria fatura.
DEFAULT_ICMS: Final = 0.0
DEFAULT_PIS: Final = 0.0
DEFAULT_COFINS: Final = 0.0
DEFAULT_PIS_COFINS_SEM_ICMS: Final = True
DEFAULT_CIP_COSIP: Final = 0.0
DEFAULT_DIA_LEITURA: Final = 1
MIN_DIA_LEITURA: Final = 1
# 28 evita o dia inexistente em fevereiro e o "pulo" de fim de mês.
MAX_DIA_LEITURA: Final = 28
DEFAULT_UPDATE_INTERVAL_HOURS: Final = 12
MIN_UPDATE_INTERVAL_HOURS: Final = 6
DEFAULT_DETALHE: Final = NAO_SE_APLICA
DEFAULT_SUBGRUPO: Final = "B1"
DEFAULT_CLASSE: Final = "Residencial"
DEFAULT_SUBCLASSE: Final = "Residencial"
# A janela de ponta é definida por cada distribuidora (RN 1000/2021);
# o padrão abaixo é apenas um chute razoável que o usuário pode ajustar.
DEFAULT_PONTA_INICIO: Final = "17:30"
DEFAULT_PONTA_FIM: Final = "20:30"

# ---------------------------------------------------------------------------
# Unidades e limites
# ---------------------------------------------------------------------------
# TUSD, TE e adicional de bandeira são publicados em R$/MWh; a normalização
# para os cálculos e entidades é em R$/kWh (divisão por 1000).
UNIT_PRECO_ENERGIA: Final = "BRL/kWh"
UNIT_REAIS: Final = "BRL"
RSMWH_PARA_RSKWH: Final = 1000.0

REQUEST_TIMEOUT: Final = 30
STORE_KEY: Final = "tarifas_aneel_cache"
STORE_VERSION: Final = 1
# Baseline do ciclo de leitura (sensores de consumo/injeção), por entry.
STORE_KEY_CICLO: Final = "tarifas_aneel_ciclo"
STORE_VERSION_CICLO: Final = 1
# Abre repair issue se ficar mais de 7 dias apenas com cache.
REPAIR_CACHE_MAX_AGE_DAYS: Final = 7
# Lembrete não bloqueante de revisão de impostos a cada 60 dias (ou quando
# um novo reajuste começa a valer).
REVISAO_IMPOSTOS_DIAS: Final = 60
# Binary sensor "dados_desatualizados" se a última atualização real tiver
# mais de 3 dias.
STALE_DATA_DAYS: Final = 3

# ---------------------------------------------------------------------------
# Atributos comuns das entidades (Fase 5)
# ---------------------------------------------------------------------------
ATTR_FONTE_DADO: Final = "fonte_dado"
ATTR_DATA_COMPETENCIA: Final = "data_competencia"
ATTR_DISTRIBUIDORA: Final = "distribuidora"
ATTR_SUBGRUPO: Final = "subgrupo"
ATTR_MODALIDADE: Final = "modalidade"
ATTR_ALIQUOTAS_APLICADAS: Final = "aliquotas_aplicadas"
ATTR_IMPOSTOS_CONFIGURADOS: Final = "impostos_configurados"
ATTR_ALIQUOTAS_REVISADAS_EM: Final = "aliquotas_revisadas_em"
ATTR_PIS_COFINS_SEM_ICMS: Final = "pis_cofins_sem_icms"
ATTR_POSTO_TARIFARIO: Final = "posto_tarifario"
ATTR_TARIFA_POR_POSTO: Final = "tarifa_por_posto"
# Atributos do custo estimado por ciclo de leitura.
ATTR_DIA_LEITURA: Final = "dia_leitura"
ATTR_CICLO_INICIO: Final = "ciclo_inicio"
ATTR_CICLO_FIM: Final = "ciclo_fim"
ATTR_CONSUMO_KWH: Final = "consumo_kwh"
ATTR_INJECAO_KWH: Final = "injecao_kwh"
ATTR_CONSUMO_LIQUIDO_KWH: Final = "consumo_liquido_kwh"
ATTR_RESET_DETECTADO: Final = "reset_detectado"
ATTR_COMPENSACAO_CONSIDERADA: Final = "compensacao_considerada"
ATTR_CREDITOS_NAO_CONSIDERADOS: Final = "creditos_nao_considerados"

DEVICE_MANUFACTURER: Final = "Dados Abertos ANEEL"

# ---------------------------------------------------------------------------
# Distribuidoras: siglas reais conforme retornadas pela API (Fase 0).
# A sigla "Não Informado" existe no dataset e é excluída do seletor.
# Há grafias duplicadas no dataset (ex.: "RGE" com dois CNPJs e
# "CPFL Santa Cruz"/"CPFL SANTA CRUZ"); ambas são mantidas para que o
# filtro por SigAgente continue válido.
# ---------------------------------------------------------------------------
DISTRIBUTORS: Final[tuple[str, ...]] = (
    "Âmbar Amazonas",
    "Âmbar Roraima",
    "CASTRO-DIS",
    "CERAL ANITÁPOLIS",
    "CERAL ARARUAMA",
    "CERAL-DIS",
    "Ceraçá",
    "CERBRANORTE",
    "CERCI",
    "CERCOS",
    "CERFOX",
    "CERGAL",
    "CERGAPA",
    "CEGERO",
    "CERGRAL",
    "CERILUZ",
    "CERIM",
    "CERIPa",
    "CERIS",
    "CERMC",
    "CERMISSÕES",
    "CERMOFUL",
    "CERNHE",
    "CERPALO",
    "CERPRO",
    "CERR",
    "CERRP",
    "CERSAD DISTRIBUI",
    "CERSUL",
    "CERTAJA",
    "CERTEL ENERGIA",
    "CERTHIL",
    "CERTREL",
    "CERVAM",
    "CEA",
    "CEEE-D",
    "CEJAMA",
    "CELESC",
    "CELETRO",
    "CEMIG-D",
    "CEMIRIM",
    "CEDRAP",
    "CEDRI",
    "CEPRAG",
    "CEREJ",
    "CERES",
    "CETRIL",
    "CFLO",
    "CHESP",
    "CNEE",
    "COCEL",
    "CODESAM",
    "COELBA",
    "COOPERALIANÇA",
    "COOPERA",
    "COOPERCOCAL",
    "COOPERLUZ",
    "COOPERMILA",
    "COOPERNORTE",
    "COOPERSUL",
    "COOPERZEM",
    "COPEL-DIS",
    "COORSEL",
    "COPREL",
    "COSERN",
    "CPFL JAGUARI",
    "CPFL LESTE PAULI",
    "CPFL MOCOCA",
    "CPFL SANTA CRUZ",
    "CPFL SUL PAULIST",
    "CPFL Santa Cruz",
    "CPFL-PAULISTA",
    "CPFL-PIRATINING",
    "CRELUZ-D",
    "DCELT",
    "DEMEI",
    "DMED",
    "EAC",
    "EBO",
    "EDEVP",
    "EDP ES",
    "EDP SP",
    "EEB",
    "EFLJC",
    "EFLUL",
    "ELEKTRO",
    "ELETROCAR",
    "ELETROPAULO",
    "ELFSM",
    "EMR",
    "EMT",
    "EMS",
    "ENEL CE",
    "ENEL RJ",
    "ENF",
    "EPB",
    "EQUATORIAL AL",
    "EQUATORIAL GO",
    "EQUATORIAL MA",
    "EQUATORIAL PA",
    "EQUATORIAL PI",
    "ERO",
    "ESE",
    "ESS",
    "ETO",
    "HIDROPAN",
    "LIGHT SESA",
    "MUXENERGIA",
    "Neoenergia Brasília",
    "Neoenergia PE",
    "PACTO ENERGIA PR",
    "RGE",
    "RGE SUL",
    "SULGIPE",
    "UHENPAL",
)

# Nome amigável para as principais distribuidoras. Siglas sem entrada no
# dicionário são exibidas como estão (o usuário as reconhece pela sigla).
DISTRIBUTOR_NAMES: Final[dict[str, str]] = {
    "Âmbar Amazonas": "Âmbar Amazonas (AM)",
    "Âmbar Roraima": "Âmbar Roraima (RR)",
    "CEEE-D": "CEEE Equatorial (RS)",
    "CELESC": "Celesc (SC)",
    "CEMIG-D": "CEMIG Distribuição (MG)",
    "COELBA": "Coelba (BA)",
    "COPEL-DIS": "Copel Distribuição (PR)",
    "COSERN": "Cosern (RN)",
    "CPFL JAGUARI": "CPFL Jaguari (SP)",
    "CPFL LESTE PAULI": "CPFL Leste Paulista (SP)",
    "CPFL MOCOCA": "CPFL Mococa (SP)",
    "CPFL SANTA CRUZ": "CPFL Santa Cruz (SP)",
    "CPFL SUL PAULIST": "CPFL Sul Paulista (SP)",
    "CPFL Santa Cruz": "CPFL Santa Cruz (SP)",
    "CPFL-PAULISTA": "CPFL Paulista (SP)",
    "CPFL-PIRATINING": "CPFL Piratininga (SP)",
    "ELEKTRO": "Elektro (SP)",
    "ELETROPAULO": "Enel Distribuição São Paulo (SP)",
    "EMS": "Energisa Mato Grosso do Sul (MS)",
    "EMT": "Energisa Mato Grosso (MT)",
    "ENEL CE": "Enel Distribuição Ceará (CE)",
    "ENEL RJ": "Enel Distribuição Rio (RJ)",
    "EDP ES": "EDP Espírito Santo (ES)",
    "EDP SP": "EDP São Paulo (SP)",
    "EQUATORIAL AL": "Equatorial Alagoas (AL)",
    "EQUATORIAL GO": "Equatorial Goiás (GO)",
    "EQUATORIAL MA": "Equatorial Maranhão (MA)",
    "EQUATORIAL PA": "Equatorial Pará (PA)",
    "EQUATORIAL PI": "Equatorial Piauí (PI)",
    "ERO": "Equatorial Roraima (RR)",
    "LIGHT SESA": "Light (RJ)",
    "Neoenergia Brasília": "Neoenergia Brasília (DF)",
    "Neoenergia PE": "Neoenergia Celpe (PE)",
    "RGE": "RGE (RS)",
    "RGE SUL": "RGE Sul (RS)",
}
