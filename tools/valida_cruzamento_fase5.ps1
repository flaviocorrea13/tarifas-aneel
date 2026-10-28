# Cruzamento: simbolos importados de custom_components.tarifas_aneel.* vs arquivos de origem.
$base = 'D:\Documentos\Documents\GitHub\tarifas_aneel\custom_components\tarifas_aneel'
$base = 'D:\Documentos\Documents\GitHub\tarifas-aneel\custom_components\tarifas_aneel'
$consumers = @('__init__.py','entity.py','sensor.py','binary_sensor.py','button.py','coordinator.py','diagnostics.py')
$modulos = @('const','models','api','calc','coordinator','entity')

# carrega fontes dos modulos
$fonte = @{}
foreach ($m in $modulos) {
  $fonte[$m] = [System.IO.File]::ReadAllText((Join-Path $base ($m + '.py')))
}

$falhas = 0
foreach ($c in $consumers) {
  $text = [System.IO.File]::ReadAllText((Join-Path $base $c))
  # blocos: from custom_components.tarifas_aneel.<mod> import (\n ... \n)
  $rx = "from custom_components\.tarifas_aneel\.(\w+) import \(([\s\S]*?)\)"
  foreach ($m in [regex]::Matches($text, $rx)) {
    $mod = $m.Groups[1].Value
    $simbolos = $m.Groups[2].Value -split ',' | ForEach-Object {
      $s = $_.Trim()
      if ($s -match '^(\w+)\s+as\s+\w+$') { $Matches[1] } elseif ($s -match '^\w+$') { $s }
    } | Where-Object { $_ }
    foreach ($s in $simbolos) {
      $ok = $false
      if ($fonte.ContainsKey($mod)) {
        $src = $fonte[$mod]
        if ($src -match ('\bclass\s+' + $s + '\b')) { $ok = $true }
        elseif ($src -match ('\bdef\s+' + $s + '\b')) { $ok = $true }
        elseif ($src -match ('\b' + $s + '\s*[:=]')) { $ok = $true }
      }
      if (-not $ok) {
        Write-Output ("{0}: SIMBOLO INEXISTENTE '{1}' em {2}.py" -f $c, $s, $mod)
        $falhas++
      }
    }
  }
  # imports single-line: from ... import X, Y
  $rx1 = "from custom_components\.tarifas_aneel\.(\w+) import ([^\(\n]+)$"
  foreach ($m in [regex]::Matches($text, $rx1, 'Multiline')) {
    $mod = $m.Groups[1].Value
    $simbolos = $m.Groups[2].Value -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ -match '^\w+$' }
    foreach ($s in $simbolos) {
      $ok = $false
      if ($fonte.ContainsKey($mod)) {
        $src = $fonte[$mod]
        if ($src -match ('\bclass\s+' + $s + '\b')) { $ok = $true }
        elseif ($src -match ('\bdef\s+' + $s + '\b')) { $ok = $true }
        elseif ($src -match ('\b' + $s + '\s*[:=]')) { $ok = $true }
      }
      if (-not $ok) {
        Write-Output ("{0}: SIMBOLO INEXISTENTE (1 linha) '{1}' em {2}.py" -f $c, $s, $mod)
        $falhas++
      }
    }
  }
}
if ($falhas -eq 0) { Write-Output "CRUZAMENTO OK: todos os simbolos importados existem nas fontes" } else { Write-Output ("TOTAL DE FALHAS: {0}" -f $falhas) }
