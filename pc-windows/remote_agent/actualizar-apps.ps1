# JARVIS: mete todas las apps instaladas del PC en la lista de apps que puede abrir, con nombres cortos (sin ventanas).
$ErrorActionPreference = 'SilentlyContinue'
$e = 'C:\jarvis_agent\remote_agent\.env'; $d = 'C:\jarvis_agent\apps'
New-Item -ItemType Directory -Force $d | Out-Null
$bad = '(?i)uninstall|desinstal|powershell|^cmd|s.mbolo del sistema|terminal|regedit|registro|bazzite|recovery|recuperaci|herramientas de windows|windows tools|administra|defender|seguridad de windows|firewall'
$generic = '^(app|apps|help|ayuda|update|updater|manager|settings|launcher|setup|tools|readme|documentation|website|online|the|de|del|la|el|for|and)$'
$apps = [ordered]@{}
function Add-A($k, $t) { $k = ($k -replace '\s+', ' ').Trim(); if ($k.Length -ge 2 -and -not $apps.Contains($k)) { $apps[$k] = $t } }
foreach ($a in Get-StartApps) {
  $n = ($a.Name.ToLower() -replace '[;="]', ' ' -replace '\(.*?\)', ' ' -replace '\s+', ' ').Trim()
  if (-not $n -or $n -match $bad -or $a.AppID -match '^https?:') { continue }
  $slug = (($n.Normalize([Text.NormalizationForm]::FormD) -replace '\p{Mn}', '') -replace '[^a-z0-9]+', '-').Trim('-')
  if (-not $slug) { continue }
  $f = "$d\$slug.vbs"; $id = $a.AppID -replace '"', '""'
  Set-Content $f "CreateObject(""Shell.Application"").ShellExecute ""shell:AppsFolder\$id""" -Encoding Unicode
  $t = "wscript.exe $f"
  $n2 = $n -replace '^(microsoft|google|mozilla|adobe|valve|epic games) ', ''
  Add-A $n $t; Add-A $n2 $t
  $w = @($n2 -split ' ' | Where-Object { $_ })
  if ($w.Count -ge 2) {
    $ini = (($w[0..($w.Count - 2)] | ForEach-Object { $_.Substring(0, 1) }) -join '')
    Add-A "$ini $($w[-1])" $t; Add-A "$ini$($w[-1])" $t; Add-A (($w | ForEach-Object { $_.Substring(0, 1) }) -join '') $t
    foreach ($x in @($w[-1], $w[0])) { if ($x.Length -ge 4 -and $x -notmatch $generic -and $x -notmatch '^\d') { Add-A $x $t } }
  }
}
$L = [IO.File]::ReadAllLines($e); $i = -1
for ($j = 0; $j -lt $L.Count; $j++) { if ($L[$j] -match '^APPS=') { $i = $j; break } }
$cur = if ($i -ge 0) { ($L[$i] -replace '^APPS=', '').Trim().Trim('"') } else { '' }
$keep = [ordered]@{}
foreach ($p in ($cur -split ';')) { $q = $p.IndexOf('='); if ($q -gt 0) { $keep[$p.Substring(0, $q).Trim()] = $p.Substring($q + 1) } }
foreach ($k in $apps.Keys) { if (-not $keep.Contains($k)) { $keep[$k] = $apps[$k] } }
$line = 'APPS="' + (($keep.Keys | ForEach-Object { "$_=$($keep[$_])" }) -join ';') + '"'
if ($i -ge 0) { $L[$i] = $line } else { $L += $line }
[IO.File]::WriteAllLines($e, [string[]]$L)
"nombres que JARVIS entiende: $($keep.Count)"
