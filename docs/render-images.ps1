# Regenerate every image in docs/images: Mermaid diagrams, eval charts (SVG), and PNG copies
# of the charts for dev.to and Medium (which don't take SVG uploads).
#
#   pwsh docs/render-images.ps1                      # from the repo root
#   pwsh docs/render-images.ps1 -Runs v1:heldout     # charts for other eval runs
#
# Needs: Node (npx, for mermaid-cli), uv, and Microsoft Edge or Google Chrome (headless, to
# rasterize SVG). Nothing here calls a model API: it's all free.

param(
    [string[]]$Runs = @("v1:heldout", "v11:fresh:v1.1")
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$images = Join-Path $PSScriptRoot "images"
New-Item -ItemType Directory -Force $images | Out-Null

Write-Host "Diagrams (Mermaid -> PNG)"
Get-ChildItem (Join-Path $PSScriptRoot "diagrams\*.mmd") | ForEach-Object {
    $out = Join-Path $images ($_.BaseName + ".png")
    npx -y @mermaid-js/mermaid-cli@11 -i $_.FullName -o $out -b white -s 2 -q
    Write-Host "  $($_.BaseName).png"
}

Write-Host "Eval charts (dashboard.json -> SVG)"
Push-Location (Join-Path $root "backend")
try {
    uv run --no-sync acr eval charts @Runs --out $images
} finally {
    Pop-Location
}

$browser = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $browser) {
    Write-Warning "No Edge or Chrome found: SVG charts written, PNG copies skipped."
    exit 0
}

Write-Host "Chart PNGs (SVG -> PNG at 2x)"
$profile = Join-Path ([IO.Path]::GetTempPath()) "acr-render-profile"
Get-ChildItem (Join-Path $images "eval-*.svg") | ForEach-Object {
    $svg = Get-Content $_.FullName -Raw
    if ($svg -notmatch 'width="(\d+)" height="(\d+)"') { throw "no size in $($_.Name)" }
    $png = $_.FullName -replace '\.svg$', '.png'
    $url = "file:///" + ($_.FullName -replace '\\', '/')
    # The browser logs harmless noise to stderr, which Windows PowerShell 5.1 would turn
    # into a terminating error under "Stop"; judge success by the file instead.
    $ErrorActionPreference = "Continue"
    & $browser --headless=new --disable-gpu --no-first-run --hide-scrollbars `
        "--user-data-dir=$profile" --force-device-scale-factor=2 `
        "--window-size=$($Matches[1]),$($Matches[2])" "--screenshot=$png" $url 2>$null | Out-Null
    $ErrorActionPreference = "Stop"
    if (-not (Test-Path $png)) { throw "no PNG written for $($_.Name)" }
    Write-Host "  $($_.BaseName).png"
}
