$ErrorActionPreference = 'Stop'
$taskComfyFolder = (Read-Host 'ComfyUI folder (contains main.py), or portable parent').Trim('"')
$taskComfyPath = (Resolve-Path -LiteralPath $taskComfyFolder).Path
if (-not (Test-Path -LiteralPath (Join-Path $taskComfyPath 'main.py'))) {
    $taskComfyPath = Join-Path $taskComfyPath 'ComfyUI'
}
if (-not (Test-Path -LiteralPath (Join-Path $taskComfyPath 'main.py'))) {
    throw 'main.py was not found. Select your actual ComfyUI installation folder.'
}
$taskEmbeddedPython = Join-Path (Split-Path -Parent $taskComfyPath) 'python_embeded/python.exe'
$taskInstaller = Join-Path $PSScriptRoot 'install.py'
if (Test-Path -LiteralPath $taskEmbeddedPython) {
    & $taskEmbeddedPython -B $taskInstaller --comfy $taskComfyPath
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 -B $taskInstaller --comfy $taskComfyPath
} else {
    & python -B $taskInstaller --comfy $taskComfyPath
}
if ($LASTEXITCODE -ne 0) { throw 'Installation stopped. Read the message above; existing packs were not overwritten.' }
Write-Host 'Node files installed. Follow INSTALL_KO.md for Python dependencies and model files.'
Read-Host 'Press Enter to close'
