# Sync index.md (GitHub Pages source of truth) -> README.md (GitHub repo view with blob URLs)
$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$indexPath = Join-Path $root "index.md"
$readmePath = Join-Path $root "README.md"
$base = "https://github.com/zlatko-lakisic/zlatko-lakisic/blob/main"

if (-not (Test-Path $indexPath)) {
    Write-Error "Missing $indexPath"
}

$content = Get-Content $indexPath -Raw -Encoding UTF8

# Relative markdown links -> GitHub blob URLs (order matters: anchors before bare paths)
$replacements = @(
    @{ Pattern = '\]\(/zlatko-lakisic/Projects\.html#([^)]+)\)'; Replacement = "]($base/Projects.md#`$1)" }
    @{ Pattern = '\]\(/zlatko-lakisic/Projects\.html\)'; Replacement = "]($base/Projects.md)" }
    @{ Pattern = '\]\(\./Resume\.md#'; Replacement = "]($base/Resume.md#" }
    @{ Pattern = '\]\(\./Resume\.md\)'; Replacement = "]($base/Resume.md)" }
    @{ Pattern = '\]\(\./Technical-Strategy\.md#'; Replacement = "]($base/Technical-Strategy.md#" }
    @{ Pattern = '\]\(\./Technical-Strategy\.md\)'; Replacement = "]($base/Technical-Strategy.md)" }
    @{ Pattern = '\]\(\./Recommendations/README\.md\)'; Replacement = "]($base/Recommendations/README.md)" }
    @{ Pattern = '\]\(\./Recommendations/([^)#]+)\)'; Replacement = "]($base/Recommendations/`$1)" }
    @{ Pattern = '\]\(\./Writing/README\.md\)'; Replacement = "]($base/Writing/README.md)" }
    @{ Pattern = '\]\(\./Writing/([^)#]+)\)'; Replacement = "]($base/Writing/`$1)" }
    @{ Pattern = '\]\(\./Projects\.md#([^)]+)\)'; Replacement = "]($base/Projects.md#`$1)" }
    @{ Pattern = '\]\(\./Projects\.md\)'; Replacement = "]($base/Projects.md)" }
    @{ Pattern = '\]\(\./Engineering/([^)#]+)\)'; Replacement = "]($base/Engineering/`$1)" }
    @{ Pattern = '\]\(\./Healthcare/([^)#]+)\)'; Replacement = "]($base/Healthcare/`$1)" }
    @{ Pattern = '\]\(\./Identity/([^)#]+)\)'; Replacement = "]($base/Identity/`$1)" }
    @{ Pattern = '\]\(\./White-Papers/([^)#]+)\)'; Replacement = "]($base/White-Papers/`$1)" }
    @{ Pattern = '\]\(\./index\.md\)'; Replacement = "]($base/index.md)" }
    @{ Pattern = '\]\(LICENSE\)'; Replacement = "]($base/LICENSE)" }
    @{ Pattern = 'href="\./Projects\.md#([^"]+)"'; Replacement = "href=""$base/Projects.md#`$1""" }
    @{ Pattern = 'href="\./Engineering/([^"]+)"'; Replacement = "href=""$base/Engineering/`$1""" }
)

foreach ($r in $replacements) {
    $content = [regex]::Replace($content, $r.Pattern, $r.Replacement)
}

$pagesCta = "**[View formatted portfolio on GitHub Pages →](https://zlatko-lakisic.github.io/zlatko-lakisic/)** — case studies and deep dives with the Minimal theme.`n"
$needle = "**Private Networks Architect & Practice Lead · Enterprise Presales & Connected Solutions**`n"
if ($content.Contains($needle) -and -not $content.Contains($pagesCta.Trim())) {
    $content = $content.Replace($needle, $needle + "`n" + $pagesCta)
}

$header = @"
<!-- AUTO-GENERATED from index.md. Do not edit README.md directly. Run: scripts/sync-readme.ps1 -->

"@

Set-Content -Path $readmePath -Value ($header + $content) -Encoding UTF8 -NoNewline
Write-Host "Synced README.md from index.md"
