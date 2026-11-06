# Changelog

Todas as mudanças notáveis da integração **Tarifas ANEEL** são registradas
neste arquivo. O formato segue o
[Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o projeto usa
versionamento semântico.

## [1.2.0] - 2026-11-06

**Confiabilidade e configuração.** Esta versão não altera as fórmulas
tarifárias: o foco é diagnóstico, reconfiguração, nomes de dispositivos e
qualidade dos testes.

### Adicionado

- Fluxo de **reconfiguração** do recorte tarifário: altera distribuidora,
  subgrupo, classe, subclasse, modalidade e detalhe sem apagar a entry. O
  `unique_id`, o título e os dados são atualizados e a integração recarrega
  ao final; uma combinação já usada por outra entry é recusada.
- Sensores de **vigência** da tarifa (início e fim) e de **diagnóstico**:
  fonte do dado da tarifa, fonte do dado da bandeira, última atualização
  real e **idade do dado** em dias.
- Atributos `ultimo_erro` (primeira linha do erro, até 200 caracteres) e
  `ultima_atualizacao_sucesso` nos sensores de preço.
- Botão **Limpar cache e atualizar**, que apaga o cache persistente e força
  uma busca real na ANEEL.
- Sufixo **(subgrupo • modalidade)** no nome do dispositivo quando há mais
  de uma entry da mesma distribuidora.
- Diagnóstico exportável seguro: uma falha ao montar o payload nunca
  derruba o recurso de diagnóstico.
- Caso numérico de referência no harness do Home Assistant, com TE
  `0,32459`, TUSD `0,66201`, ICMS 17%, PIS 1,65% e COFINS 7,6% sobre a base
  sem ICMS (`≈ 1,3098 R$/kWh`).
- Suíte de testes com `pytest-homeassistant-custom-component` e CI em
  matriz: Home Assistant 2024.10 (Python 3.12) e versão estável
  (Python 3.14), além dos jobs de ruff, hassfest e HACS.

### Corrigido

- Diagnóstico no Home Assistant 2024.10: o recurso não depende mais de
  `last_update_success_time` (inexistente na versão mínima) e usa o
  timestamp próprio do coordinator.
- Timestamp da última atualização real separado do `last_update_success`
  do coordinator, preservado pelo cache e sobrevivendo a reinícios.
- Setup em duas fases: o cache é publicado imediatamente e a busca real
  roda em segundo plano com backoff de 5, 15 e 60 minutos. Recarregar a
  entry preserva a fonte real já obtida (API/CSV).
- Reconfiguração no Home Assistant 2024.10: os dados atuais da entry não
  são mais tratados como uma submissão do usuário no primeiro passo.
- `_abort_if_unique_id_mismatch` (inexistente no HA 2024.10) foi
  substituído por `_abort_if_unique_id_configured` na criação da entry.
- Nome do dispositivo duplicado quando duas entries usam a mesma
  distribuidora.
- Documentação alinhada: o intervalo mínimo de atualização é 6 h e o
  limiar de dados desatualizados é 3 dias, ambos centralizados em
  `const.py`.

### Alterado

- `unique_id` das entidades passou a ser baseado em `entry.entry_id`, então
  trocar o recorte na reconfiguração não cria entidades órfãs.
- Traduções pt-BR e en para reconfiguração, idade do dado, limpeza de cache
  e novos diagnósticos.
- README revisado com reconfiguração, entidades de diagnóstico, idade do
  dado, botão de limpeza de cache e instruções de teste.

### Testes

- 167 testes passando no Home Assistant 2024.10.0 e no 2026.10.4.
- `ruff`, `compileall`, hassfest e validação do HACS sem erros.

## [1.1.0] - 2026-10-29

### Adicionado

- Setup **cache-first**: publica o cache na inicialização e busca API/CSV
  em segundo plano.
- Custo estimado do **ciclo de leitura**, com baseline persistida,
  detecção de reset do medidor e compensação de injeção.
- Seletores de sensores de energia e do dia da leitura (1 a 28).
- Reaplicação das opções em memória, sem nova busca de rede.

### Corrigido

- Fórmula de impostos: PIS/COFINS passou a incidir sobre a base sem ICMS
  por padrão, com opção para a fórmula antiga e validação das alíquotas.
- Lembrete de revisão de impostos e atributos de transparência
  (`impostos_configurados`, `aliquotas_revisadas_em`,
  `pis_cofins_sem_icms`).
- README reescrito em pt-BR, com glossário, diagramas e exemplos de
  automação.

## [1.0.0] - 2026-10-28

### Adicionado

- Primeira versão pública da integração.
- Consulta de TUSD, TE e bandeira tarifária nos dados abertos da ANEEL.
- Fallback em três camadas (API JSON, CSV e cache persistente).
- Cálculo do preço final com ICMS, PIS/COFINS, bandeira e CIP/COSIP.
- Entidades de tarifa, bandeira, status da API e dados desatualizados.
