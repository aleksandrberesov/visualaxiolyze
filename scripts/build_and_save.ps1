param(
    [string]$ImageName = "visualaxiolyze",
    [string]$Tag = ""
)

# Resolve tag from pyproject.toml if not supplied
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

$TarFile = "$ImageName`_$Tag.tar"

Write-Host "Updating submodules..." -ForegroundColor Cyan
git submodule update --init --recursive

Write-Host "Building Docker image: ${ImageName}:$Tag..." -ForegroundColor Cyan
docker build -t "${ImageName}:$Tag" .

if ($LASTEXITCODE -eq 0) {
    Write-Host "Saving Docker image to $TarFile..." -ForegroundColor Cyan
    docker save -o $TarFile "${ImageName}:$Tag"
    Write-Host "Done! Image saved as $TarFile" -ForegroundColor Green
} else {
    Write-Error "Docker build failed."
}
