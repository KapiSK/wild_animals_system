param()
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    $latex = Get-Command platex -ErrorAction Stop
    $converter = Get-Command dvipdfmx -ErrorAction Stop
    $outputDir = 'out/bthesis'
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
    for ($pass = 1; $pass -le 3; $pass++) {
        $logFile = Join-Path $outputDir "compile-pass-$pass.txt"
        $ErrorActionPreference = 'Continue'
        & $latex.Source '-kanji=utf8' '-interaction=nonstopmode' '-halt-on-error' '-file-line-error' "-output-directory=$outputDir" 'main.tex' *> $logFile
        $ErrorActionPreference = 'Stop'
        if ($LASTEXITCODE -ne 0) {
            Get-Content -LiteralPath $logFile -Tail 60
            throw "pLaTeX failed on pass $pass."
        }
    }
    $ErrorActionPreference = 'Continue'
    & $converter.Source '-o' "$outputDir/main.pdf" "$outputDir/main.dvi" *> "$outputDir/dvipdfmx.txt"
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) {
        Get-Content -LiteralPath "$outputDir/dvipdfmx.txt" -Tail 60
        throw 'dvipdfmx failed.'
    }
    Copy-Item -LiteralPath "$outputDir/main.pdf" -Destination 'main.pdf' -Force
    Write-Output "Built: $(Join-Path $PSScriptRoot 'main.pdf')"
} finally { Pop-Location }
