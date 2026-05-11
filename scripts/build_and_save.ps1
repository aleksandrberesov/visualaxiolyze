$ImageName = "visualaxiolyze"
$Tag = "latest"
$TarFile = "$ImageName`_$Tag.tar"

Write-Host "Updating submodules..." -ForegroundColor Cyan
git submodule update --init --recursive

Write-Host "Building Docker image: $ImageName:$Tag..." -ForegroundColor Cyan
docker build -t "$ImageName:$Tag" .

if ($LASTEXITCODE -eq 0) {
    Write-Host "Saving Docker image to $TarFile..." -ForegroundColor Cyan
    docker save -o $TarFile "$ImageName:$Tag"
    Write-Host "Done! Image saved as $TarFile" -ForegroundColor Green
} else {
    Write-Error "Docker build failed."
}
