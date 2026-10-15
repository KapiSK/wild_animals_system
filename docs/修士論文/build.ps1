param()
$ErrorActionPreference = 'Stop'
$previousTexmfVar = $env:TEXMFVAR
$previousTexmfCache = $env:TEXMFCACHE
Push-Location -LiteralPath $PSScriptRoot
try {
    $latex = Get-Command lualatex -ErrorAction Stop
    New-Item -ItemType Directory -Path 'out' -Force | Out-Null
    # Keep generated font caches within this project, including in restricted environments.
    $cachePath = Join-Path $PSScriptRoot 'out/tex-cache'
    New-Item -ItemType Directory -Path $cachePath -Force | Out-Null
    $env:TEXMFVAR = $cachePath
    $env:TEXMFCACHE = $cachePath
    # Three passes resolve the contents, page numbers, and cross-references.
    for ($pass = 1; $pass -le 3; $pass++) {
        $logFile = Join-Path 'out' "compile-pass-$pass.txt"
        & $latex.Source '-interaction=nonstopmode' '-halt-on-error' '-file-line-error' '-output-directory=out' 'main.tex' *> $logFile
        if ($LASTEXITCODE -ne 0) {
            Get-Content -LiteralPath $logFile -Tail 60
            throw "LuaLaTeX failed on pass $pass. See $logFile."
        }
    }
    Copy-Item -LiteralPath 'out/main.pdf' -Destination 'main.pdf' -Force
    Write-Output "Built: $(Join-Path $PSScriptRoot 'main.pdf')"
} finally {
    $env:TEXMFVAR = $previousTexmfVar
    $env:TEXMFCACHE = $previousTexmfCache
    Pop-Location
}
