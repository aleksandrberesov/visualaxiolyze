param(
    [string]$ImageName = "visualaxiolyze",
    [string]$Tag = "",
    [string]$OutputDir = ""
)

# Resolve base version from pyproject.toml if not supplied
if (-not $Tag) {
    $pyproject = Join-Path $PSScriptRoot "..\deps\repo_vdag\pyproject.toml"
    $versionLine = Select-String -Path $pyproject -Pattern '^version\s*=\s*"(.+)"' | Select-Object -First 1
    if ($versionLine) {
        $Tag = $versionLine.Matches[0].Groups[1].Value
        Write-Host "Detected version: $Tag" -ForegroundColor DarkGray
    } else {
        Write-Error "Could not read version from $pyproject. Pass -Tag explicitly."
        exit 1
    }
}

# Compute build number as the sum of commits across all project repos so any
# commit to any repo (main, repo_vdag, repo_glm) increments the number.
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
function _CountCommits([string]$p) {
    $n = git -C $p rev-list --count HEAD 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $n) { return 0 }
    return [int]$n.Trim()
}
$BuildNumber = (_CountCommits $Root) + (_CountCommits (Join-Path $Root "deps\repo_vdag")) + (_CountCommits (Join-Path $Root "deps\repo_glm"))
Write-Host "Build number: $BuildNumber" -ForegroundColor DarkGray

# Append build number to tag so the image is uniquely identified
$Tag = "$Tag.$BuildNumber"
Write-Host "Full tag: $Tag" -ForegroundColor DarkGray

$TarName = "$ImageName`_$Tag.tar"
if ($OutputDir) {
    if (-not (Test-Path $OutputDir)) {
        New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    }
    $TarFile = Join-Path $OutputDir $TarName
} else {
    $TarFile = $TarName
}

Write-Host "Updating submodules..." -ForegroundColor Cyan
git submodule update --init --recursive

Write-Host "Building Docker image: ${ImageName}:$Tag..." -ForegroundColor Cyan
docker build --build-arg BUILD_NUMBER=$BuildNumber -t "${ImageName}:$Tag" .

if ($LASTEXITCODE -eq 0) {
    Write-Host "Saving Docker image to $TarFile..." -ForegroundColor Cyan
    docker save -o $TarFile "${ImageName}:$Tag"
    Write-Host "Done! Image saved as $TarFile" -ForegroundColor Green
} else {
    Write-Error "Docker build failed."
}
