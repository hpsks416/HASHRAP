$ErrorActionPreference = 'Stop'
$taskSettings = Join-Path $PSScriptRoot 'desktop-settings.json'
if (-not (Test-Path -LiteralPath $taskSettings)) { $taskSettings = Join-Path $env:LOCALAPPDATA 'ChipManualDesk/desktop-settings.json' }
if (-not (Test-Path -LiteralPath $taskSettings)) { throw 'Run Install.cmd first.' }
$taskConfig = Get-Content -LiteralPath $taskSettings -Raw -Encoding UTF8 | ConvertFrom-Json
$env:PYTHONUTF8 = '1'
$env:CHIPRAG_DATA = $taskConfig.library_root
Push-Location $taskConfig.backend
try { & $taskConfig.python -m chiprag.cli configure-ai --app-root $taskConfig.app_root; $taskExit = $LASTEXITCODE } finally { Pop-Location }
exit $taskExit
