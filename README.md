# Tarifas ANEEL — integração para o Home Assistant

[![Validate](https://github.com/flaviocorrea13/tarifas-aneel/actions/workflows/validate.yml/badge.svg)](https://github.com/flaviocorrea13/tarifas-aneel/actions/workflows/validate.yml)
[![Tests](https://github.com/flaviocorrea13/tarifas-aneel/actions/workflows/tests.yml/badge.svg)](https://github.com/flaviocorrea13/tarifas-aneel/actions/workflows/tests.yml)

Consulta **tarifas de aplicação (TUSD/TE)** e **bandeiras tarifárias** das
distribuidoras brasileiras no
[Portal de Dados Abertos da ANEEL](https://dadosabertos.aneel.gov.br),
aplica os impostos da sua fatura (gross-up "por dentro") e expõe o
**preço final em R$/kWh** — pronto para o
[painel de Energia](https://www.home-assistant.io/dashboards/energy/) medir
quanto você paga por kWh consumido.

Uma entry da integração = um **recorte tarifário**: distribuidora +
subgrupo + classe + subclasse + modalidade (+ detalhe SCEE).

## Recursos

* **Preço final em R$/kWh** (entidade `tarifa_final`), com
  desmembramento TUSD, TE, gross-up de impostos e adicional de bandeira.
* **Modalidade Branca**: o preço acompanha o posto tarifário ativo em
  cada momento (Ponta, Intermediário, Fora ponta), com janela de ponta
  configurável.
* **Bandeira tarifária vigente** (Verde, Amarela, Vermelha P1/P2), com
  fallback automático para o mês anterior quando a ANEEL ainda não
  publicou o mês corrente.
* **Cobertura**: 114 distribuidoras (siglas usadas pela ANEEL), com
  foco no Grupo B — a integração é pensada para unidades residenciais
  (B1/B2/B3/B4).
* **Instalação HACS** (repositório customizado) e suporte a telas de
  diagnóstico e repair issues do Home Assistant.
* **Resiliência**: cascata de camadas oficial JSON → CSV de dados abertos
  → cache local persistente (sobrevive a reinícios e a quedas do portal).

## Instalação

### HACS (recomendado)

1. Instale o [HACS](https://hacs.xyz/) no seu Home Assistant.
2. HACS → Integrações → menu → **Repositório personalizado**.
3. Cole `https://github.com/flaviocorrea13/tarifas-aneel`, categoria
   **Integration**.
4. Instale a integração **Tarifas ANEEL**.
5. Reinicie o Home Assistant.

### Manual

Copie o diretório `custom_components/tarifas_aneel` para dentro de
`config/custom_components/` do seu Home Assistant e reinicie.

## Configuração

Configurações → Integrações → **Adicionar integração** → **Tarifas ANEEL**.

O recorte é **validado na base da ANEEL antes de criar a entry** — se
nenhuma tarifa estiver publicada para o recorte, o Home Assistant
acusa "sem dados" e a entry não é criada.

| Campo | Descrição |
|---|---|
| **Distribuidora** | Dropdown com 114 siglas (rótulos amigáveis; grafias com rótulo repetido aparecem com a sigla entre colchetes). |
| **Subgrupo** | Grupo tarifário da fatura (padrão **B1**; o seletor cobre A1–AS e B–B4). |
| **Classe** | Classe de consumo (padrão **Residencial**). |
| **Subclasse** | Subclasse de consumo (padrão **Residencial**; inclui Tarifa Social, Baixa Renda, Iluminação pública – B4a/B4b…). |
| **Modalidade** | **Convencional** ou **Branca** (única coberta aqui — Grupo B). |
| **Detalhe** | "Não se aplica" (padrão) ou **SCEE** (TE reduzida para unidades com geração distribuída). |

O `unique_id` do recorte é `distribuidora_subgrupo_modalidade` (com o
detalhe SCEE sufixado quando diferente do padrão) — por isso uma entry
normal e uma variante SCEE do mesmo recorte coexistem sem duplicação.

## Opções

Configurações → Integrações → **Tarifas ANEEL** → ⚙️ **Configurar**.

Mudanças nas opções **recarregam** a entry automaticamente; automações
e histórico não se perdem.

| Opção | Padrão | Descrição |
|---|---|---|
| **ICMS (%)** | 0 | Alíquota de ICMS da sua fatura (ex.: 18). Aplicada no gross-up "por dentro". |
| **PIS (%)** | 0 | Alíquota de PIS (ex.: 0,65). |
| **COFINS (%)** | 0 | Alíquota de COFINS (ex.: 3,64). |
| **CIP/COSIP (R$/mês)** | 0 | Custo fixo mensal (sensor informativo separado). |
| **Intervalo de atualização (h)** | 12 | Frequência de consulta à ANEEL (mínimo 6 h). |
| **Sensor de consumo (kWh)** | — | Sensor de consumo opcional, para automações. |
| **Início/Fim da ponta** | 17:30 / 20:30 | Só aparece na modalidade Branca (janela de ponta da distribuidora). |

> As alíquotas começam em **0 de propósito**: copie os valores reais da
> **sua fatura** (bloco de impostos), pois a soma embutida muda o preço.
> A regra não deixa a soma passar de 100%.

## Entidades

Um device **Tarifas ANEEL** por entry (com link direto para o portal da
ANEEL), contendo:

| Entidade | Descrição |
|---|---|
| `sensor.…_tarifa_final` | **Preço final em R$/kWh** (impostos + bandeira) — é esta que o painel de Energia usa. Na Branca, acompanha o posto ativo e expõe `tarifa_por_posto` nos atributos. |
| `sensor.…_tarifa_sem_impostos` | TUSD + TE, antes dos impostos e da bandeira. |
| `sensor.…_tarifa_tusd` | Tarifa de uso do sistema de distribuição. |
| `sensor.…_tarifa_te` | Tarifa de energia. |
| `sensor.…_adicional_bandeira` | Adicional da bandeira vigente, em R$/kWh. |
| `sensor.…_bandeira_tarifaria` | Nome da bandeira acionada (Verde, Amarela, Vermelha P1/P2…). |
| `sensor.…_posto_tarifario` | Posto ativo em cada momento (só modalidade Branca). |
| `sensor.…_cip_cosip_mensal` | CIP/COSIP configurada, em R$/mês. |
| `binary_sensor.…_dados_desatualizados` | **Ligado** quando a última atualização real (API/CSV) tem mais de 3 dias — indica valor servido só do cache. |
| `button.…_atualizar_agora` | Força um ciclo imediato do coordinator. |

`available` das entidades de tarifa só some quando TODAS as camadas
falharam (incluindo o cache). Falhas parciais (ex.: bandeira
indisponível) mantêm entidades disponíveis, apenas sem o adicional.

## Painel de Energia

1. Configurações → Integrações → **Tarifas ANEEL** → configure o recorte
   (subgrupo, classe, subclasse) da sua unidade.
2. Painel de Energia → **Definir tarifas** → escolha o **preço** 
   `sensor.…_tarifa_final`.
3. O painel multiplica seu consumo (kWh) pelo valor atual (R$/kWh) e
   soma o custo total.

### Requisitos da moeda (importante!)

* Para o painel de Energia aceitar e calcular corretamente, a
  **moeda do Home Assistant deve ser BRL** — Configurações → Sistema →
  Geral → Moeda.

### O que (não) entra no R$/kWh

* **Entra**: TUSD + TE + adicional da bandeira, sob gross-up "por
  dentro" das alíquotas configuradas (ICMS + PIS + COFINS).
* **Não entra**: **CIP/COSIP** (custo fixo mensal — sensor separado,
  informativo) e outros custos não tarifários listados na fatura.

## Como a integração funciona

1. **Vigência por data**: a tarifa de aplicação vale por período de
   vigência (não é mensal); se nenhuma vigência estiver corrente, a
   tarifa mais recente é aplicada provisoriamente até o próximo
   reajuste publicado.
2. **Bandeira mensal**: consultada pela competência do mês; se a ANEEL
   ainda não publicou a bandeira acionada, usa o mês anterior como
   fallback automático e marca `mes_anterior: true` nos atributos.
3. **Fallback em 3 camadas (independente por dado)**:
   1. **JSON oficial** — `datastore_search` (CKAN) com filtros
      server-side e paginação;
   2. **CSV de dados abertos** — `datastore/dump/<resource_id>` com os
      mesmos filtros;
   3. **Cache local persistente** — `Store` (sobrevive a reinícios);
      o repair issue `dados_apenas_cache` é aberto se ficar mais de
      7 dias só com cache e fechado quando dados reais voltam.
4. **Unidades**: valores publicados em R$/MWh (energia) são normalizados
   de graça no cliente, para R$/kWh; tarifas de demanda em kW são
   ignoradas.

## Notas técnicas

* **Compatível com 2024.10 → atual**: usa `entry.runtime_data`,
  `translation_key`, `DeviceInfo`, config/options flow com
  `MINOR_VERSION` e sem APIs deprecadas (como atribuir
  `self.config_entry`).
* `unique_id` das entidades: `<entry_id>_<sufixo>` estável.
* **Diagnóstico**: Configurações → Integrações → Tarifas ANEEL →
  ⋮ → Exportar diagnósticos.
* **Recursos da base**: `dadosabertos.aneel.gov.br` —
  tarifas de aplicação
  `fcf2906c-7c32-4b9b-a637-054e7a5234f4`,
  bandeira acionada `0591b8f6-fe54-437b-b72b-1aa2efd46e42`,
  adicional de bandeira
  `5879ca80-b3bd-45b1-a135-d9b77c1d5b36`.

## Problemas comuns

* **"Sem dados" na criação**: o recorte não existe literalmente no
  dataset. Confira subgrupo (B1? B4?), classe/subclasse exatos da
  fatura e se o detalhe SCEE precisa ser ligado.
* **Preço 0**: alíquotas padrão — o preço final é tarifa sem impostos
  (TUSD+TE). Configure ICMS/PIS/COFINS nas opções.
* **Integração não encontrada**: reinicie o HA após a instalação e
  confira o diretório `custom_components/tarifas_aneel`.

## Desenvolvimento

```bash
pip install homeassistant==2024.10.0 pytest python-dateutil pyyaml
pytest tests -q
```

Lint:

```bash
pip install ruff
ruff check custom_components tests
```

O CI roda ruff, hassfest e a validação do HACS a cada push/PR e os
testes no Python 3.12 com o HA 2024.10.

## Licença

[MIT](LICENSE)
