param(
    [string]$PythonPath = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $repositoryRoot $PythonPath
$entryPoint = Join-Path $repositoryRoot "src\lead_enrichment\gui\app.py"
$distributionDirectory = Join-Path $repositoryRoot "dist"
$executable = Join-Path $distributionDirectory "AdBeamPersonParser.exe"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python virtual environment was not found: $python"
}

& $python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw 'PyInstaller is not installed. Run: .\.venv\Scripts\python.exe -m pip install -e ".[build]"'
}

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "AdBeamPersonParser" `
    --paths (Join-Path $repositoryRoot "src") `
    --collect-all "selectolax" `
    $entryPoint

if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "PyInstaller did not create the expected executable"
}

$hash = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash
$size = (Get-Item -LiteralPath $executable).Length
Write-Output "Executable: $executable"
Write-Output "Size: $size bytes"
Write-Output "SHA256: $hash"
