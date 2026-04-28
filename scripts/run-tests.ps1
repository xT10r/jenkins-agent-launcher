[CmdletBinding()]
param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs = @("tests", "-v"),

    [Parameter()]
    [string]$BaseTempRoot = "",

    [Parameter()]
    [switch]$KeepTemp,

    [Parameter()]
    [switch]$UseWorkspaceTemp
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Remove-TestDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    try {
        attrib -R "$Path" /S /D 2>$null | Out-Null
    } catch {
    }

    try {
        icacls $Path /inheritance:e /T /C 2>$null | Out-Null
        icacls $Path /reset /T /C 2>$null | Out-Null
        icacls $Path /remove:d Everyone /T /C 2>$null | Out-Null
        icacls $Path /remove:d '*S-1-1-0' /T /C 2>$null | Out-Null
    } catch {
    }

    try {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
        return
    } catch {
    }

    try {
        cmd /c "rd /s /q ""$Path""" | Out-Null
    } catch {
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = (Resolve-Path (Join-Path $scriptDir "..")).Path
$venvPython = Join-Path $projectDir "venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "venv не найден: $venvPython. Сначала запустите scripts\setup.bat."
}

if ([string]::IsNullOrWhiteSpace($BaseTempRoot)) {
    if ($UseWorkspaceTemp) {
        $BaseTempRoot = Join-Path $projectDir ".tmp\pytest"
    } else {
        $localAppData = [Environment]::GetFolderPath("LocalApplicationData")
        $BaseTempRoot = Join-Path $localAppData "jenkins-agent-launcher\pytest"
    }
}

$null = New-Item -ItemType Directory -Force -Path $BaseTempRoot

$runId = "{0:yyyyMMdd-HHmmss}-{1}" -f (Get-Date), $PID
$baseTemp = Join-Path $BaseTempRoot $runId
$null = New-Item -ItemType Directory -Force -Path $baseTemp

$env:TEMP = $baseTemp
$env:TMP = $baseTemp

$resolvedPytestArgs = @()
if ($PytestArgs.Count -gt 0) {
    $resolvedPytestArgs += $PytestArgs
}

$resolvedPytestArgs += "--basetemp=$baseTemp"
$resolvedPytestArgs += "--cache-clear"

Write-Host "ProjectDir : $projectDir"
Write-Host "Python     : $venvPython"
Write-Host "BaseTemp   : $baseTemp"
Write-Host "PytestArgs : $($resolvedPytestArgs -join ' ')"
Write-Host ""

Push-Location $projectDir
try {
    & $venvPython -m pytest @resolvedPytestArgs
    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location

    if ($KeepTemp) {
        Write-Warning "Временный каталог сохранён: $baseTemp"
    } else {
        Remove-TestDirectory -Path $baseTemp
    }
}

if ($null -eq $exitCode) {
    $exitCode = 1
}

exit $exitCode
