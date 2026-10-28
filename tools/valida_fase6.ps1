# Validacao Fase 6: JSONs, estrutura de traducoes, placeholders, manifest.
$pkg = 'D:\Documentos\Documents\GitHub\tarifas-aneel\custom_components\tarifas_aneel'
$fail = 0

function Fail($msg) { Write-Output ("FALHA: " + $msg); $script:fail++ }
function Ok($msg) { Write-Output ("OK: " + $msg) }

# --- 1. Parse JSON ---
$arquivos = @('manifest.json', 'strings.json', 'translations\pt-BR.json', 'translations\en.json')
$dados = @{}
foreach ($a in $arquivos) {
  $p = Join-Path $pkg $a
  try {
    $dados[$a] = Get-Content $p -Raw -Encoding UTF8 | ConvertFrom-Json
    Ok ("JSON valido: " + $a)
  } catch {
    Fail ("JSON invalido: " + $a + " -> " + $_.Exception.Message)
  }
}
if ($fail -gt 0) { return }

function KeyPaths($obj, $prefix = '') {
  if ($obj -is [System.Management.Automation.PSCustomObject]) {
    foreach ($p in $obj.PSObject.Properties) {
      $path = if ($prefix) { "$prefix.$($p.Name)" } else { $p.Name }
      $path
      if ($p.Value -is [System.Management.Automation.PSCustomObject]) {
        KeyPaths $p.Value $path
      }
    }
  }
}

# --- 2. strings.json == pt-BR.json (conteudo) ---
$s = $dados['strings.json'] | ConvertTo-Json -Depth 20 -Compress
$p = $dados['translations\pt-BR.json'] | ConvertTo-Json -Depth 20 -Compress
if ($s -eq $p) { Ok 'strings.json e pt-BR.json identicos' } else { Fail 'strings.json difere de pt-BR.json' }

# --- 3. en.json tem o mesmo conjunto de chaves de strings.json ---
$ks = @(KeyPaths $dados['strings.json'] | Sort-Object -Unique)
$ke = @(KeyPaths $dados['translations\en.json'] | Sort-Object -Unique)
if ((Compare-Object $ks $ke).Count -eq 0) { Ok 'en.json: mesmo conjunto de chaves de strings.json' } else {
  Fail 'en.json: chaves divergentes: ' + ((Compare-Object $ks $ke | ForEach-Object { $_.InputObject }) -join '; ')
}

# --- 4. Chaves esperadas dos steps ---
$esperadoUser = @('distribuidora','subgrupo','classe','subclasse','modalidade','detalhe')
$esperadoOpt = @('icms_percentual','pis_percentual','cofins_percentual','cip_cosip_mensal','update_interval_horas','consumo_entity_id','ponta_inicio','ponta_fim')
$userData = @($dados['strings.json'].config.step.user.data.PSObject.Properties.Name)
$optData = @($dados['strings.json'].options.step.init.data.PSObject.Properties.Name)
if ((Compare-Object $userData $esperadoUser).Count -eq 0) { Ok 'config.step.user.data: 6 chaves corretas' } else { Fail ('user.data: ' + ($userData -join ',')) }
if ((Compare-Object $optData $esperadoOpt).Count -eq 0) { Ok 'options.step.init.data: 8 chaves corretas' } else { Fail ('init.data: ' + ($optData -join ',')) }

# data_description cobre as mesmas chaves
$userDD = @($dados['strings.json'].config.step.user.data_description.PSObject.Properties.Name)
$optDD = @($dados['strings.json'].options.step.init.data_description.PSObject.Properties.Name)
if ((Compare-Object $userDD $esperadoUser).Count -eq 0) { Ok 'user.data_description: chaves completas' } else { Fail 'user.data_description incompleto' }
if ((Compare-Object $optDD $esperadoOpt).Count -eq 0) { Ok 'init.data_description: chaves completas' } else { Fail 'init.data_description incompleto' }

# --- 5. errors / abort / issues ---
$cfgErr = @($dados['strings.json'].config.error.PSObject.Properties.Name)
$optErr = @($dados['strings.json'].options.error.PSObject.Properties.Name)
$abort = @($dados['strings.json'].config.abort.PSObject.Properties.Name)
if (($cfgErr -contains 'sem_dados') -and ($cfgErr -contains 'cannot_connect') -and $cfgErr.Count -eq 2) { Ok 'config.error: sem_dados + cannot_connect' } else { Fail ('config.error: ' + ($cfgErr -join ',')) }
if (($optErr -contains 'soma_aliquotas') -and $optErr.Count -eq 1) { Ok 'options.error: soma_aliquotas' } else { Fail ('options.error: ' + ($optErr -join ',')) }
if (($abort -contains 'already_configured') -and $abort.Count -eq 1) { Ok 'config.abort: already_configured' } else { Fail ('config.abort: ' + ($abort -join ',')) }
$issue = $dados['strings.json'].issues.dados_apenas_cache
if ($issue -and $issue.title -and $issue.description) {
  $d = $issue.description
  if ($d.Contains('{dias}') -and $d.Contains('{ultima}') -and $d.Contains('{distribuidora}')) { Ok 'issue dados_apenas_cache com placeholders dias/ultima/distribuidora' } else { Fail 'issue sem placeholders esperados' }
} else { Fail 'issues.dados_apenas_cache ausente/incompleto' }

# --- 6. entity.* contra translation_keys do codigo ---
$chavesEsperadas = @{
  'sensor'        = @('tarifa_final','tarifa_sem_impostos','tarifa_tusd','tarifa_te','adicional_bandeira','bandeira_atual','posto_tarifario','custo_fixo_mensal')
  'binary_sensor' = @('dados_desatualizados')
  'button'        = @('atualizar_agora')
}
foreach ($plat in $chavesEsperadas.Keys) {
  $no = @($dados['strings.json'].entity.$plat.PSObject.Properties.Name)
  if ((Compare-Object $no $chavesEsperadas[$plat]).Count -eq 0) { Ok ("entity.$plat : chaves corretas") } else { Fail ("entity.$plat : " + ($no -join ',')) }
}
# cada chave aparece no codigo (como literal)
$pys = Get-ChildItem $pkg -Filter '*.py' | Select-Object -ExpandProperty FullName
foreach ($k in ($chavesEsperadas.Values | ForEach-Object { $_ })) {
  $achou = $false
  foreach ($py in $pys) {
    if ((Select-String -Path $py -Pattern ('"' + $k + '"') -SimpleMatch -Quiet)) { $achou = $true; break }
  }
  if ($achou) { Ok ("chave usada no codigo: " + $k) } else { Fail ("chave NAO usada no codigo: " + $k) }
}

# --- 7. manifest ---
$m = $dados['manifest.json']
if ($m.codeowners -contains '@flaviocorrea13') { Ok 'manifest codeowners: @flaviocorrea13' } else { Fail 'manifest codeowners errado' }
if ($m.documentation -eq 'https://github.com/flaviocorrea13/tarifas-aneel') { Ok 'manifest documentation OK' } else { Fail 'manifest documentation errado' }
if ($m.issue_tracker -eq 'https://github.com/flaviocorrea13/tarifas-aneel/issues') { Ok 'manifest issue_tracker OK' } else { Fail 'manifest issue_tracker errado' }

# --- 8. Sem leftovers de placeholder ---
$left = Get-ChildItem 'D:\Documentos\Documents\GitHub\tarifas-aneel' -Recurse -File |
  Where-Object { $_.FullName -notmatch '\\tools\\' } |
  Select-String -Pattern 'SEU-USUARIO' -SimpleMatch
if ($left) { Fail ('placeholder restante em: ' + (($left | ForEach-Object { $_.Path }) -join '; ')) } else { Ok 'sem placeholders @SEU-USUARIO restantes' }

Write-Output ""
if ($fail -eq 0) { Write-Output '=== FASE 6: TODAS AS VALIDACOES JSON/ESTRUTURA PASSARAM ===' } else { Write-Output ("=== FASE 6: {0} FALHA(S) ===" -f $fail) }
