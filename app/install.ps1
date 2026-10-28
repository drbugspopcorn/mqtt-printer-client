<#
    Installs (or re-installs) the MQTT printer client as a Windows service.  Safe to re-run - keeps app\.env.

    Fresh PC - paste into an *Administrator* PowerShell:
        & ([scriptblock]::Create((irm https://raw.githubusercontent.com/drbugspopcorn/mqtt-printer-client/master/app/install.ps1))) -Broker docker-host-esxi.local -Name packing-3

    Existing checkout:
        powershell -ExecutionPolicy Bypass -File C:\mqtt-printer-client\app\install.ps1

    Everything it downloads is pinned and lives under the install folder (nothing added to PATH):
        Python (machine-wide, only if a usable one isn't already installed), MinGit for updates,
        SumatraPDF for silent PDF printing, WinSW to run it as a service.
#>
param(
    [string]$Broker = '',
    [int]$Port = 0,
    [string]$Name = '',
    [string]$Dir = '',
    [string]$Branch = 'master'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'    # Invoke-WebRequest crawls with the progress bar on
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$RepoUrl = 'https://github.com/drbugspopcorn/mqtt-printer-client.git'
$ServiceId = 'printer-client'
$PythonVersion = '3.12.10'
$PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-amd64.exe"
$MinGitUrl = 'https://github.com/git-for-windows/git/releases/download/v2.56.0.windows.2/MinGit-2.56.0.2-64-bit.zip'
$SumatraUrl = 'https://www.sumatrapdfreader.org/dl/rel/3.5.2/SumatraPDF-3.5.2-64.zip'
$WinSWUrl = 'https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe'

function Step($message) { Write-Host "==> $message" -ForegroundColor Cyan }

function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$(Split-Path $Exe -Leaf) $($Arguments -join ' ') failed (exit $LASTEXITCODE)" }
}

function Get-File($Url, $Destination) {
    Write-Host "    downloading $Url"
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Destination
}

function Find-Python {
    # Windows PowerShell turns a native command's redirected stderr into a terminating error under 'Stop'
    $ErrorActionPreference = 'Continue'
    $candidates = @(
        "$env:ProgramFiles\Python313\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python311\python.exe",
        "$env:ProgramFiles\Python310\python.exe"
    )
    foreach ($candidate in $candidates) { if (Test-Path $candidate) { return $candidate } }
    # py launcher - skip the Microsoft Store stub and per-user installs the service account can't rely on
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        $exe = & py.exe -3 -c "import sys; print(sys.executable if sys.version_info >= (3, 8) else '')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe -and (Test-Path $exe) -and $exe -notmatch 'WindowsApps|\\Users\\') { return $exe }
    }
    return $null
}

function X($Value) { [Security.SecurityElement]::Escape([string]$Value) }

function Write-Utf8NoBom($Path, $Text) {
    # PowerShell 5's -Encoding utf8 adds a BOM, which breaks the first key in .env
    [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding($false)))
}

function Set-EnvValue($Text, $Key, $Value) {
    if ($Text -match "(?m)^#?\s*$Key=.*$") { return $Text -replace "(?m)^#?\s*$Key=.*$", "$Key=$Value" }
    return $Text.TrimEnd() + "`r`n$Key=$Value`r`n"
}

# --- checks ---

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this from an Administrator PowerShell (right-click PowerShell > Run as administrator)'
}
if (-not [Environment]::Is64BitOperatingSystem) { throw 'Needs 64-bit Windows' }

if (-not $Dir) {
    if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot 'printer_client.py'))) {
        $Dir = Split-Path $PSScriptRoot -Parent
    } else {
        $Dir = 'C:\mqtt-printer-client'
    }
}
$AppDir = Join-Path $Dir 'app'
$Tools = Join-Path $Dir 'tools'
$Temp = Join-Path $env:TEMP "printer-client-install"
New-Item -ItemType Directory -Force -Path $Temp | Out-Null

# --- Python ---

Step 'Python'
$Python = Find-Python
if (-not $Python) {
    $installer = Join-Path $Temp "python-$PythonVersion-amd64.exe"
    Get-File $PythonUrl $installer
    Write-Host "    installing Python $PythonVersion for all users (takes a minute)"
    $process = Start-Process -FilePath $installer -Wait -PassThru -ArgumentList @(
        '/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_test=0', 'Include_launcher=1', 'Shortcuts=0')
    if ($process.ExitCode -ne 0) { throw "Python installer failed (exit $($process.ExitCode))" }
    $Python = Find-Python
    if (-not $Python) { throw "Python installed but couldn't be found under $env:ProgramFiles" }
}
Write-Host "    using $Python"

# --- git (portable, just for this) ---

Step 'Git'
$Git = Join-Path $Tools 'git\cmd\git.exe'
$GitStaging = Join-Path $Temp 'git'
if (-not (Test-Path $Git)) {
    # unpacked to temp first - $Dir has to be empty for a fresh clone
    Get-File $MinGitUrl (Join-Path $Temp 'mingit.zip')
    Expand-Archive -Path (Join-Path $Temp 'mingit.zip') -DestinationPath $GitStaging -Force
}
$GitNow = if (Test-Path $Git) { $Git } else { Join-Path $GitStaging 'cmd\git.exe' }

# --- code ---

Step "Code in $Dir"
if (-not (Test-Path (Join-Path $Dir '.git'))) {
    if ((Test-Path $Dir) -and (Get-ChildItem $Dir -Force | Where-Object { $_.Name -ne 'tools' })) {
        throw "$Dir already exists and isn't a checkout of the printer client - move it or pass -Dir"
    }
    $cloneTarget = Join-Path $Temp 'checkout'
    if (Test-Path $cloneTarget) { Remove-Item -Recurse -Force $cloneTarget }
    Invoke-Native $GitNow @('clone', '-q', '-c', 'core.autocrlf=false', '-b', $Branch, $RepoUrl, $cloneTarget)
    New-Item -ItemType Directory -Force -Path $Dir | Out-Null
    Get-ChildItem $cloneTarget -Force | Move-Item -Destination $Dir -Force
}
if (-not (Test-Path $Git)) {
    New-Item -ItemType Directory -Force -Path $Tools | Out-Null
    Move-Item $GitStaging (Join-Path $Tools 'git') -Force
}
# the service runs as LocalSystem, which git otherwise refuses to trust with a repo an admin cloned
$safeDir = $Dir -replace '\\', '/'
$ErrorActionPreference = 'Continue'
$trusted = & $Git config --system --get-all safe.directory 2>$null
$ErrorActionPreference = 'Stop'
if ($trusted -notcontains $safeDir) { Invoke-Native $Git @('config', '--system', '--add', 'safe.directory', $safeDir) }
# --replace-all: git on Windows already writes filemode on clone, and a plain set refuses duplicates
Invoke-Native $Git @('-C', $Dir, 'config', '--replace-all', 'core.fileMode', 'false')
Invoke-Native $Git @('-C', $Dir, 'config', '--replace-all', 'core.autocrlf', 'false')

# --- Python environment ---

Step 'Python packages'
$Venv = Join-Path $Dir '.venv'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path $VenvPython)) { Invoke-Native $Python @('-m', 'venv', $Venv) }
Invoke-Native $VenvPython @('-m', 'pip', 'install', '-q', '--disable-pip-version-check', '-r', (Join-Path $AppDir 'requirements.common.txt'))

# --- SumatraPDF (silent PDF printing) ---

Step 'SumatraPDF'
$Sumatra = Join-Path $Tools 'SumatraPDF.exe'
if (-not (Test-Path $Sumatra)) {
    $zip = Join-Path $Temp 'sumatra.zip'
    Get-File $SumatraUrl $zip
    $staging = Join-Path $Temp 'sumatra'
    Expand-Archive -Path $zip -DestinationPath $staging -Force
    Copy-Item (Get-ChildItem $staging -Filter 'SumatraPDF*.exe' | Select-Object -First 1).FullName $Sumatra
}

# --- config ---

Step 'Config'
$EnvFile = Join-Path $AppDir '.env'
if (Test-Path $EnvFile) {
    $envText = [IO.File]::ReadAllText($EnvFile)
} else {
    $envText = [IO.File]::ReadAllText((Join-Path $AppDir 'example.env'))
    if (-not $Name) { $Name = $env:COMPUTERNAME.ToLower() }
}
if ($Name) { $envText = Set-EnvValue $envText 'CLIENT_NAME' (($Name -replace '[^A-Za-z0-9_-]', '-')) }
if ($Broker) { $envText = Set-EnvValue $envText 'MQTT_BROKER_ADDRESS' $Broker }
if ($Port) { $envText = Set-EnvValue $envText 'MQTT_BROKER_PORT' $Port }
Write-Utf8NoBom $EnvFile $envText
New-Item -ItemType Directory -Force -Path (Join-Path $AppDir 'docs_tmp') | Out-Null

# --- service ---

Step 'Windows service'
$ServiceExe = Join-Path $Tools "$ServiceId-service.exe"
$ServiceXml = Join-Path $Tools "$ServiceId-service.xml"
$Logs = Join-Path $Dir 'logs'
New-Item -ItemType Directory -Force -Path $Logs | Out-Null

$existing = Get-Service -Name $ServiceId -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host '    removing the existing service'
    if ($existing.Status -ne 'Stopped') { Stop-Service -Name $ServiceId -Force }
    if (Test-Path $ServiceExe) { & $ServiceExe uninstall | Out-Null } else { sc.exe delete $ServiceId | Out-Null }
    Start-Sleep -Seconds 2
}
if (-not (Test-Path $ServiceExe)) { Get-File $WinSWUrl $ServiceExe }

# services only see the machine PATH from boot, so hand ours over explicitly (git for updates, powershell for printer setup)
$servicePath = "$Tools\git\cmd;$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\WindowsPowerShell\v1.0;" +
    [Environment]::GetEnvironmentVariable('Path', 'Machine')
$xml = @"
<service>
  <id>$ServiceId</id>
  <name>Printer Client (MQTT)</name>
  <description>Prints jobs from the OMS over MQTT and reports to the fleet page. $(X $Dir)</description>
  <executable>$(X $VenvPython)</executable>
  <arguments>-u $(X ('"' + (Join-Path $AppDir 'launcher.py') + '"'))</arguments>
  <workingdirectory>$(X $AppDir)</workingdirectory>
  <env name="PATH" value="$(X $servicePath)" />
  <env name="PYTHONUTF8" value="1" />
  <startmode>Automatic</startmode>
  <delayedAutoStart>true</delayedAutoStart>
  <onfailure action="restart" delay="5 sec" />
  <resetfailure>1 hour</resetfailure>
  <stoptimeout>20 sec</stoptimeout>
  <logpath>$(X $Logs)</logpath>
  <log mode="roll-by-size">
    <sizeThreshold>5120</sizeThreshold>
    <keepFiles>4</keepFiles>
  </log>
</service>
"@
Write-Utf8NoBom $ServiceXml $xml
Invoke-Native $ServiceExe @('install')
try {
    Start-Service -Name $ServiceId
} catch {
    Write-Host "Service didn't start: $_" -ForegroundColor Red
    Get-ChildItem $Logs -Filter '*.log' | ForEach-Object { Write-Host "--- $($_.Name)"; Get-Content $_.FullName -Tail 20 }
    throw
}

Start-Sleep -Seconds 5
$service = Get-Service -Name $ServiceId
Remove-Item -Recurse -Force $Temp -ErrorAction SilentlyContinue

Write-Host ''
Write-Host "Installed.  Service: $($service.Status)" -ForegroundColor Green
Write-Host "Config:  $EnvFile"
Select-String -Path $EnvFile -Pattern '^(CLIENT_NAME|MQTT_BROKER_ADDRESS|MQTT_BROKER_PORT)=' | ForEach-Object { Write-Host "         $($_.Line)" }
Write-Host "Logs:    $Logs\$ServiceId-service.out.log"
Write-Host 'Printers need to be installed on this PC (USB, or a network printer added by IP) - printers mapped from'
Write-Host 'another PC (\\otherpc\printer) are invisible to the service.  Then pick them from the OMS Printers page.'
