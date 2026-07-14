# 대시보드 API Lambda(dashboard_api) 배포 패키지(zip) 생성 스크립트
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$build = Join-Path $root "build_dashboard"
$zip = Join-Path $root "dashboard_lambda_deploy.zip"
$handler = Join-Path $root "lambda\dashboard_api\handler.py"

if (Test-Path $build) { Remove-Item $build -Recurse -Force }
if (Test-Path $zip) { Remove-Item $zip -Force }
New-Item -ItemType Directory -Path $build | Out-Null
Copy-Item $handler $build
Copy-Item (Join-Path $root "src") (Join-Path $build "src") -Recurse
Get-ChildItem $build -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Compress-Archive -Path (Join-Path $build "*") -DestinationPath $zip -Force
Remove-Item $build -Recurse -Force
Write-Host "완료: $zip"
