<#
.SYNOPSIS
    Recomputes APP_BUILD_NUMBER as the sum of all commit counts across every
    project repo (main + repo_vdag + repo_glm) and writes it to .env.

    Run this after any commit to any repo before launching the app or building
    the Docker image. The number grows whenever any repo gains a commit.
#>

$Root    = Resolve-Path (Join-Path $PSScriptRoot "..")
$EnvFile = Join-Path $Root ".env"

function Get-CommitCount([string]$RepoPath) {
    $n = git -C $RepoPath rev-list --count HEAD 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $n) { return 0 }
    return [int]$n.Trim()
}

$counts = @{
    "main"      = Get-CommitCount $Root
    "repo_vdag" = Get-CommitCount (Join-Path $Root "deps\repo_vdag")
    "repo_glm"  = Get-CommitCount (Join-Path $Root "deps\repo_glm")
}

$total = $counts.Values | Measure-Object -Sum | Select-Object -ExpandProperty Sum
Write-Host "Commit counts:" -ForegroundColor DarkGray
$counts.GetEnumerator() | Sort-Object Name | ForEach-Object {
    Write-Host ("  {0,-12} {1}" -f ($_.Key + ":"), $_.Value) -ForegroundColor DarkGray
}
Write-Host "APP_BUILD_NUMBER = $total" -ForegroundColor Cyan

# Read existing .env (if any), replace or append APP_BUILD_NUMBER
$lines = @()
$found = $false
if (Test-Path $EnvFile) {
    $lines = Get-Content $EnvFile
    $lines = $lines | ForEach-Object {
        if ($_ -match '^APP_BUILD_NUMBER\s*=') {
            $found = $true
            "APP_BUILD_NUMBER=$total"
        } else {
            $_
        }
    }
}
if (-not $found) { $lines += "APP_BUILD_NUMBER=$total" }

$lines | Set-Content $EnvFile -Encoding utf8
Write-Host "Updated $EnvFile" -ForegroundColor Green
