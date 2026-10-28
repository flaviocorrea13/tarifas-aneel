# Validacao: balanceamento de parens/chaves/colchetes ignorando strings e comentarios.
$files = @('__init__.py','entity.py','sensor.py','binary_sensor.py','button.py','coordinator.py','diagnostics.py')
$base = 'D:\Documentos\Documents\GitHub\tarifas-aneel\custom_components\tarifas_aneel'
$triD = '"""'
$triS = "'''"
foreach ($f in $files) {
  $path = Join-Path $base $f
  $text = [System.IO.File]::ReadAllText($path)
  $antes = $text.Length
  $text = [regex]::Replace($text, ($triD + '[\s\S]*?' + $triD), 'DOC')
  $text = [regex]::Replace($text, ($triS + '[\s\S]*?' + $triS), 'DOC')
  $out = New-Object System.Text.StringBuilder
  foreach ($line in ($text -split "`n")) {
    $semComentario = ($line -split '#')[0]
    $limpa = [regex]::Replace($semComentario, '"[^"\n]*"', 'S')
    $limpa = [regex]::Replace($limpa, "'[^'\n]*'", 'S')
    [void]$out.AppendLine($limpa)
  }
  $clean = $out.ToString()
  $problema = $false
  $pares = @(@([char]40, [char]41), @([char]123, [char]125), @([char]91, [char]93))
  foreach ($par in $pares) {
    $open = ([regex]::Matches($clean, [regex]::Escape([string]$par[0]))).Count
    $close = ([regex]::Matches($clean, [regex]::Escape([string]$par[1]))).Count
    if ($open -ne $close) {
      Write-Output ("{0}: DESEQUILIBRADO {1}={2} {3}={4}" -f $f, $par[0], $open, $par[1], $close)
      $problema = $true
    }
  }
  if (-not $problema) {
    Write-Output ("{0}: OK ({1} chars lidos, {2} apos remover docstrings)" -f $f, $antes, $text.Length)
  }
}
