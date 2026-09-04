param([Parameter(Mandatory)][string]$Installer)
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'Run this installer check only on an isolated CI runner.' }
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$installDir = Join-Path $env:LOCALAPPDATA 'Programs\Average Assistant'
$dataDir = Join-Path $env:LOCALAPPDATA 'Average Assistant'
$database = Join-Path $dataDir 'bowlers.sqlite3'
$shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'Average Assistant.lnk'
$desktopShortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Average Assistant.lnk'
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{C6DBF7E5-8D19-4F56-B443-77B0DB93A689}_is1'
if ((Test-Path -LiteralPath $installDir) -or (Test-Path -LiteralPath $dataDir)) {
    throw 'Installer check requires an empty runner profile.'
}
New-Item -ItemType Directory -Path $dataDir | Out-Null
@'
import sqlite3
import sys
with sqlite3.connect(sys.argv[1]) as connection:
    connection.execute('CREATE TABLE saved_bowlers (name TEXT)')
    connection.execute("INSERT INTO saved_bowlers VALUES ('Installer Test Bowler')")
'@ | python - $database
if ($LASTEXITCODE -ne 0) { throw 'Could not create preservation test database.' }
$before = (Get-FileHash -LiteralPath $database).Hash

function Assert-DataPreserved {
    if (!(Test-Path -LiteralPath $database) -or (Get-FileHash -LiteralPath $database).Hash -ne $before) {
        throw 'Saved bowler database changed.'
    }
}
function Run-Installer([string]$PathToExe, [string[]]$Arguments) {
    $process = Start-Process -FilePath $PathToExe -ArgumentList $Arguments -PassThru -WindowStyle Hidden
    if (!$process.WaitForExit(120000)) { throw 'Installer operation timed out.' }
    if ($process.ExitCode -ne 0) { throw "Installer operation failed: $($process.ExitCode)" }
}

# Installation and a second installation must reuse one location and preserve data.
foreach ($pass in 1..2) {
    Run-Installer $installerPath @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/TASKS=desktopicon')
    Assert-DataPreserved
    foreach ($file in @('USBC-Average-Lookup.exe', '_internal\Average-Assistant-SignIn.exe', 'unins000.exe')) {
        if (!(Test-Path -LiteralPath (Join-Path $installDir $file))) { throw "Missing installed file: $file" }
    }
    $shell = New-Object -ComObject WScript.Shell
    foreach ($link in @($shortcut, $desktopShortcut)) {
        if (!(Test-Path -LiteralPath $link)) { throw "Missing shortcut: $link" }
        if ($shell.CreateShortcut($link).TargetPath -ne (Join-Path $installDir 'USBC-Average-Lookup.exe')) {
            throw 'Shortcut points to the wrong application.'
        }
    }
    if (!(Test-Path $uninstallKey)) { throw 'Missing Windows uninstall entry.' }
}
Run-Installer (Join-Path $installDir 'unins000.exe') @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART')
# The uninstaller may finish removing its own copy immediately after returning.
for ($attempt = 0; $attempt -lt 50 -and (Test-Path -LiteralPath $shortcut); $attempt++) {
    Start-Sleep -Milliseconds 200
}
Assert-DataPreserved
foreach ($path in @($shortcut, $desktopShortcut, (Join-Path $installDir 'USBC-Average-Lookup.exe'))) {
    if (Test-Path -LiteralPath $path) { throw "Uninstall left an application item: $path" }
}
if (Test-Path $uninstallKey) { throw 'Uninstall entry was not removed.' }
Write-Output 'PASS: install, reinstall, shortcuts, uninstall entry, and saved database preservation.'
