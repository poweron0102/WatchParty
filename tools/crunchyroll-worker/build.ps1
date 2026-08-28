param([string]$Output = "..\..\bin\crunchyroll-worker.exe")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$project = $PSScriptRoot
$target = [System.IO.Path]::GetFullPath((Join-Path $project $Output))
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
Push-Location $project
try {
    $env:GOCACHE = Join-Path $project ".gocache"
    go test ./...
    $env:CGO_ENABLED = "0"
    $env:GOOS = "windows"
    $env:GOARCH = "amd64"
    go build -trimpath -ldflags="-s -w" -o $target .
} finally {
    Pop-Location
}
Write-Host "Worker criado em $target"
