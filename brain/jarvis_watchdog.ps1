<#
.SYNOPSIS
    JARVIS 24/7 Watchdog - Single unified watchdog for all JARVIS services
.DESCRIPTION
    Checks ports every 60s, restarts failed services, logs to rotating log (max 10MB),
    alerts via Telegram if any service restarts >3 times/hour.
#>

param(
    [int]$CheckInterval = 60,
    [int]$MaxLogSizeMB = 10,
    [int]$AlertThreshold = 3,
    [string]$LogPath = "{{WIN_HOME}}\jarvis2\logs\watchdog.log"
)

$ErrorActionPreference = "SilentlyContinue"

# Service definitions: name -> @{port, start_cmd, workdir, process_name}
$Services = @{
    "Ollama" = @{
        Port = 11434
        StartCmd = "ollama serve"
        WorkDir = "{{WIN_HOME}}"
        ProcessName = "ollama"
        DependsOn = @()
    }
    "OpenClaw" = @{
        Port = 18789
        StartCmd = "node gateway.js"
        WorkDir = "{{WIN_HOME}}\.openclaw"
        ProcessName = "node"
        DependsOn = @("Ollama")
    }
    "OpenJarvis" = @{
        Port = 8000
        StartCmd = "python -m openjarvis.server"
        WorkDir = "{{WIN_HOME}}\OpenJarvis"
        ProcessName = "python"
        DependsOn = @("Ollama", "OpenClaw")
    }
    "Jarvis2-Hub" = @{
        Port = 18765
        StartCmd = "python -m jarvis2.scripts.hub_service"
        WorkDir = "{{WIN_HOME}}\jarvis2"
        ProcessName = "python"
        DependsOn = @("Ollama", "OpenClaw", "OpenJarvis")
    }
    "Jarvis2-HUD" = @{
        Port = 8765
        StartCmd = "python -m jarvis2.hud.ws_server"
        WorkDir = "{{WIN_HOME}}\jarvis2"
        ProcessName = "python"
        DependsOn = @("Ollama", "OpenClaw", "OpenJarvis")
    }
}

$RestartCounts = @{}
$LastAlertTime = @{}

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $entry = "[$timestamp] [$Level] $Message"
    $entry | Out-File -FilePath $LogPath -Encoding UTF8 -Append
    Write-Host $entry
}

function Rotate-Log {
    if (Test-Path $LogPath) {
        $sizeMB = (Get-Item $LogPath).Length / 1MB
        if ($sizeMB -gt $MaxLogSizeMB) {
            $archive = "$LogPath.$(Get-Date -Format 'yyyyMMdd-HHmmss').bak"
            Move-Item $LogPath $archive -Force
            Write-Log "Log rotated: $archive (was ${sizeMB:N1}MB)"
        }
    }
}

function Test-Port {
    param([int]$Port)
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $result = $tcp.BeginConnect("127.0.0.1", $Port, $null, $null)
        $success = $result.AsyncWaitHandle.WaitOne(2000)
        $tcp.Close()
        return $success
    } catch {
        return $false
    }
}

function Start-ServiceSafe {
    param([string]$Name, [hashtable]$Svc)
    Write-Log "Starting $Name..."
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = "cmd.exe"
        $psi.Arguments = "/c $($Svc.StartCmd)"
        $psi.WorkingDirectory = $Svc.WorkDir
        $psi.WindowStyle = "Hidden"
        $psi.CreateNoWindow = $true
        $psi.UseShellExecute = $false
        $proc = [System.Diagnostics.Process]::Start($psi)
        Start-Sleep 3
        if (Test-Port $Svc.Port) {
            Write-Log "$Name started successfully (PID $($proc.Id))"
            return $true
        } else {
            Write-Log "$Name failed to start (port $($Svc.Port) not listening)" "ERROR"
            return $false
        }
    } catch {
        Write-Log "$Name start exception: $($_.Exception.Message)" "ERROR"
        return $false
    }
}

function Check-And-Restart {
    param([string]$Name, [hashtable]$Svc)
    $portOk = Test-Port $Svc.Port
    if (-not $portOk) {
        Write-Log "$Name port $($Svc.Port) DOWN - restarting..." "WARN"
        $now = Get-Date
        $hourAgo = $now.AddHours(-1)
        if (-not $RestartCounts.ContainsKey($Name)) { $RestartCounts[$Name] = @() }
        $RestartCounts[$Name] = $RestartCounts[$Name] | Where-Object { $_ -gt $hourAgo }
        $RestartCounts[$Name] += $now
        $count = $RestartCounts[$Name].Count
        if ($count -ge $AlertThreshold) {
            $lastAlert = $LastAlertTime[$Name]
            if (-not $lastAlert -or $now - $lastAlert > (New-TimeSpan -Minutes 10)) {
                Send-TelegramAlert "🚨 JARVIS Watchdog: $Name reiniciado $count veces en la última hora"
                $LastAlertTime[$Name] = $now
            }
        }
        Start-ServiceSafe $Name $Svc
    } else {
        Write-Log "$Name port $($Svc.Port) OK"
    }
}

function Send-TelegramAlert {
    param([string]$Message)
    try {
        $token = Get-Content "{{WIN_HOME}}\.openclaw\telegram-token" -ErrorAction SilentlyContinue
        $chatId = "{{CHAT_GRUPO_TELEGRAM}}"
        if ($token) {
            $url = "https://api.telegram.org/bot$token/sendMessage"
            $body = @{ chat_id = $chatId; text = $Message; parse_mode = "HTML" }
            Invoke-RestMethod -Uri $url -Method Post -Body $body -TimeoutSec 10
        }
    } catch {
        Write-Log "Telegram alert failed: $($_.Exception.Message)" "ERROR"
    }
}

function Get-SystemStatus {
    $cpu = Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average | Select-Object -ExpandProperty Average
    $ram = Get-CimInstance Win32_OperatingSystem
    $ramFree = [math]::Round($ram.FreePhysicalMemory / 1MB, 1)
    $ramTotal = [math]::Round($ram.TotalVisibleMemorySize / 1MB, 1)
    $disk = Get-PSDrive C | Select-Object @{Name='FreeGB';Expression={[math]::Round($_.Free/1GB,1)}}, @{Name='UsedGB';Expression={[math]::Round($_.Used/1GB,1)}}
    $uptime = (Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
    $svcStatus = @{}
    foreach ($name in $Services.Keys) {
        $svcStatus[$name] = if (Test-Port $Services[$name].Port) { "OK" } else { "FALLA" }
    }
    $aiModel = "desconocido"
    try {
        $resp = Invoke-RestMethod "http://127.0.0.1:11434/api/tags" -TimeoutSec 5
        if ($resp.models.Count -gt 0) { $aiModel = $resp.models[0].name }
    } catch {}
    return @{
        CPU = "$cpu%"
        RAM = "$ramFree MB / $ramTotal MB"
        Disk = "$($disk.FreeGB) GB free / $($disk.UsedGB) GB used"
        Uptime = "{0}d {1}h {2}m" -f $uptime.Days, $uptime.Hours, $uptime.Minutes
        Services = $svcStatus
        AIModel = $aiModel
    }
}

# Main loop
Write-Log "=== JARVIS Watchdog started ==="
Rotate-Log

# Initial startup in dependency order
$startupOrder = @("Ollama", "OpenClaw", "OpenJarvis", "Jarvis2-Hub", "Jarvis2-HUD")
foreach ($name in $startupOrder) {
    if (-not (Test-Port $Services[$name].Port)) {
        Start-ServiceSafe $name $Services[$name]
    }
}

while ($true) {
    Rotate-Log
    foreach ($name in $startupOrder) {
        Check-And-Restart $name $Services[$name]
    }
    Start-Sleep $CheckInterval
}