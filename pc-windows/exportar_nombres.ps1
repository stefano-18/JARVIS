# JARVIS (arreglo 74): junta los nombres de apps y juegos instalados en este PC y los manda al portatil
# para que JARVIS aprenda a pronunciarlos. Solo lee nombres; del .env lee SOLO la linea APPS.
$ErrorActionPreference = 'SilentlyContinue'
$out = Join-Path $PSScriptRoot 'nombres_pc.txt'
$n = @()
$l = [IO.File]::ReadAllLines('C:\jarvis_agent\remote_agent\.env', [Text.Encoding]::UTF8) | Where-Object { $_ -match '^\s*APPS\s*=' } | Select-Object -First 1
if ($l) {
    $n += $l.Substring($l.IndexOf('=') + 1).Trim().Trim('"', "'").Split(';') | ForEach-Object { $_.Split('=')[0].Trim() } |
        Where-Object { $_ -and $_ -notmatch '[\\/:]' -and ($_ -match '\s' -or $_.Length -ge 5) }
}
$lib = @('C:\Program Files (x86)\Steam\steamapps')
$vdf = 'C:\Program Files (x86)\Steam\steamapps\libraryfolders.vdf'
if (Test-Path $vdf) { $lib += Select-String -Path $vdf -Pattern '"path"\s+"(.+)"' | ForEach-Object { ($_.Matches[0].Groups[1].Value -replace '\\\\', '\') + '\steamapps' } }
foreach ($d in ($lib | Select-Object -Unique)) {
    Get-ChildItem "$d\appmanifest_*.acf" | ForEach-Object { $m = Select-String -Path $_.FullName -Pattern '"name"\s+"(.+)"'; if ($m) { $n += $m.Matches[0].Groups[1].Value } }
}
Get-ChildItem 'C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests\*.item' | ForEach-Object {
    $j = [IO.File]::ReadAllText($_.FullName, [Text.Encoding]::UTF8) | ConvertFrom-Json; if ($j.DisplayName) { $n += $j.DisplayName }
}
$juegos = @()
foreach ($d in ($lib | Select-Object -Unique)) {
    Get-ChildItem "$d\appmanifest_*.acf" | ForEach-Object { $m = Select-String -Path $_.FullName -Pattern '"name"\s+"(.+)"'; if ($m) { $juegos += $m.Matches[0].Groups[1].Value } }
}
Get-ChildItem 'C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests\*.item' | ForEach-Object {
    $j = [IO.File]::ReadAllText($_.FullName, [Text.Encoding]::UTF8) | ConvertFrom-Json; if ($j.DisplayName -and $j.bIsApplication -ne $false) { $juegos += $j.DisplayName }
}
$juegos = $juegos | ForEach-Object { ($_ -replace '[®™]', '').Trim() } | Where-Object { $_ -notmatch '^appid_|Redistributable|Steamworks' } | Sort-Object -Unique
$jout = Join-Path $PSScriptRoot 'juegos_pc.txt'
[IO.File]::WriteAllLines($jout, [string[]]$juegos, (New-Object Text.UTF8Encoding $false))
& scp -q -o BatchMode=yes -o ConnectTimeout=10 $jout 'jarvis:.config/jarvis/juegos_pc.txt'
$n = $n | ForEach-Object { ($_ -replace '[®™]', '' -replace '\s*\((x64|x86|wow)\)', '').Trim() } |
    Where-Object { $_.Length -ge 2 -and $_.Length -le 40 -and $_ -notmatch '^appid_|Redistributable|Steamworks' } | Sort-Object -Unique
[IO.File]::WriteAllLines($out, [string[]]$n, (New-Object Text.UTF8Encoding $false))
& scp -q -o BatchMode=yes -o ConnectTimeout=10 $out 'jarvis:.config/jarvis/nombres_pc.txt'
