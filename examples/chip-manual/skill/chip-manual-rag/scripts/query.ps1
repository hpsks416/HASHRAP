$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:CHIPRAG_DATA = 'G:\CodexDS\DSH\INTRO\HASHRAP\ChipManualDesk-1.0.2\backend\data'
$taskBackend = 'G:\CodexDS\DSH\INTRO\HASHRAP\ChipManualDesk-1.0.2\backend'
$taskPython = 'G:\CodexDS\DSH\INTRO\HASHRAP\ChipManualDesk-1.0.2\runtime\venv\Scripts\python.exe'
if ($args.Count -eq 0 -or $args[0] -notin @('status','search','read','page')) { throw 'Allowed: status, search, read, page' }
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'ChipManualDesk runtime missing. Run Install.cmd.' }
Push-Location $taskBackend
try { & $taskPython -m chiprag.cli @args; $taskExit = $LASTEXITCODE } finally { Pop-Location }
exit $taskExit
