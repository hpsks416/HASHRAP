param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'ChipManualDesk'),
    [string]$LibraryRoot = (Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'ChipManualLibrary'),
    [string]$SeedLibrary = '',
    [string]$UvCache = '',
    [switch]$SkipAiConfiguration
)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$LibraryRoot = [IO.Path]::GetFullPath($LibraryRoot)
if ($InstallRoot -eq [IO.Path]::GetPathRoot($InstallRoot) -or $LibraryRoot -eq [IO.Path]::GetPathRoot($LibraryRoot)) { throw 'Choose a dedicated application/library directory, not a drive root.' }
New-Item -ItemType Directory -Force -Path $InstallRoot,$LibraryRoot,(Join-Path $InstallRoot 'cache/tmp'),(Join-Path $InstallRoot 'runtime/python') | Out-Null
$env:TEMP = Join-Path $InstallRoot 'cache/tmp'
$env:TMP = $env:TEMP
if (-not $UvCache) { $UvCache = Join-Path $InstallRoot 'cache/uv' }
$env:UV_CACHE_DIR = $UvCache
$env:UV_PYTHON_INSTALL_DIR = Join-Path $InstallRoot 'runtime/python'
$env:UV_LINK_MODE = 'copy'
Write-Output '[1/6] Installing application files...'
foreach ($taskName in @('backend','tools','Install.ps1','Install.cmd','Configure-AI.cmd','Configure-AI.ps1','Start.cmd','使用指南.md','使用指南.html','ChipManualDesk.exe')) {
    $taskSource = Join-Path $PSScriptRoot $taskName
    $taskTarget = Join-Path $InstallRoot $taskName
    if ((Test-Path -LiteralPath $taskSource) -and ([IO.Path]::GetFullPath($taskSource) -ne [IO.Path]::GetFullPath($taskTarget))) {
        if (Test-Path -LiteralPath $taskSource -PathType Container) {
            New-Item -ItemType Directory -Force -Path $taskTarget | Out-Null
            Get-ChildItem -LiteralPath $taskSource -Force | Copy-Item -Destination $taskTarget -Recurse -Force
        } elseif (-not (Test-Path -LiteralPath $taskTarget) -or (Get-FileHash -LiteralPath $taskSource).Hash -ne (Get-FileHash -LiteralPath $taskTarget).Hash) {
            Copy-Item -LiteralPath $taskSource -Destination $taskTarget -Force
        }
    }
}
$taskUv = Join-Path $InstallRoot 'tools/uv.exe'
if (-not (Test-Path -LiteralPath $taskUv)) { throw 'tools/uv.exe missing. Extract the complete package.' }
Write-Output '[2/6] Preparing dedicated Python 3.12.14...'
& $taskUv python install 3.12.14 --install-dir $env:UV_PYTHON_INSTALL_DIR --cache-dir $UvCache --no-bin --no-registry
$taskDownloadExit = $LASTEXITCODE
$taskBasePython = Join-Path $env:UV_PYTHON_INSTALL_DIR 'cpython-3.12.14-windows-x86_64-none/python.exe'
if (-not (Test-Path -LiteralPath $taskBasePython)) { throw 'Python download incomplete. Check network and rerun Install.cmd.' }
& $taskBasePython -c "import sys; assert sys.version_info[:3] == (3,12,14); print(sys.version.split()[0])"
if ($LASTEXITCODE -ne 0) { throw 'Downloaded Python did not pass version validation.' }
if ($taskDownloadExit -ne 0) { Write-Warning 'Python is valid; an optional version-link could not be created. Continuing with the explicit application-local interpreter.' }
$taskPython = Join-Path $InstallRoot 'runtime/venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    & $taskUv venv --python $taskBasePython --cache-dir $UvCache (Join-Path $InstallRoot 'runtime/venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create runtime.' }
}
Write-Output '[3/6] Installing verified dependencies...'
& $taskUv pip install --python $taskPython --cache-dir $UvCache --link-mode copy -r (Join-Path $InstallRoot 'backend/requirements-lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; rerun to resume cached downloads.' }
Write-Output '[4/6] Configuring library and reusing existing data...'
$env:CHIPRAG_DATA = $LibraryRoot
$env:PYTHONPATH = Join-Path $InstallRoot 'backend'
if (-not $SeedLibrary) {
    $taskFound = & $taskPython -c "from chiprag.integration import find_legacy_library; print(find_legacy_library() or '')"
    if ($LASTEXITCODE -eq 0 -and $taskFound) { $SeedLibrary = $taskFound.Trim() }
}
$taskArgs = @('-m','chiprag.deployment','--app-root',$InstallRoot,'--library',$LibraryRoot)
if ($SeedLibrary) { $taskArgs += @('--seed-library',[IO.Path]::GetFullPath($SeedLibrary)) }
Push-Location (Join-Path $InstallRoot 'backend')
try {
    & $taskPython @taskArgs
    if ($LASTEXITCODE -ne 0) { throw 'Library configuration failed.' }
    if ([IO.Path]::GetFullPath($PSScriptRoot) -ne $InstallRoot) {
        try { Copy-Item -LiteralPath (Join-Path $InstallRoot 'desktop-settings.json') -Destination (Join-Path $PSScriptRoot 'desktop-settings.json') -Force } catch { Write-Warning 'Package directory is read-only; launch the EXE in the installed application directory.' }
    }
    Write-Output '[5/6] Verifying/downloading local models...'
    & $taskPython -m chiprag.cli models-verify
    if ($LASTEXITCODE -ne 0) {
        & $taskPython -m chiprag.cli models-download
        if ($LASTEXITCODE -ne 0) { throw 'Model download incomplete. Rerun to continue.' }
        & $taskPython -m chiprag.cli models-verify
        if ($LASTEXITCODE -ne 0) { throw 'Model verification failed.' }
    }
    Write-Output '[6/6] Detecting AI applications and installing supported skills...'
    if (-not $SkipAiConfiguration) {
        & $taskPython -m chiprag.cli configure-ai --app-root $InstallRoot
        if ($LASTEXITCODE -ne 0) { throw 'AI skill configuration failed. Runtime is installed; retry Configure-AI.cmd.' }
    }
} finally { Pop-Location }
Write-Output "READY: $InstallRoot\ChipManualDesk.exe"
Write-Output "LIBRARY: $LibraryRoot"
Write-Output 'Open a new Codex / Claude Code chat after skill configuration.'
