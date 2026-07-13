# 분석 Lambda(container-damage-analyzer) 배포 패키지(zip) 생성 스크립트 (Windows PowerShell)
#
# 사용법:
#   .\build_lambda.ps1
# 결과:
#   lambda_deploy.zip  (lambda_handler.py + 공유 src/ 포함)
#
# 참고: boto3 는 Lambda 런타임에 기본 포함, python-dotenv 는 선택 의존성이라
#       (config.py 가 try/except 로 처리) 패키지에 넣지 않는다.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$build = Join-Path $root "build"
$zip = Join-Path $root "lambda_deploy.zip"
$handler = Join-Path $root "lambda\container-damage-analyzer\lambda_handler.py"

Write-Host "[1/4] 이전 산출물 정리..."
if (Test-Path $build) { Remove-Item $build -Recurse -Force }
if (Test-Path $zip) { Remove-Item $zip -Force }
New-Item -ItemType Directory -Path $build | Out-Null

Write-Host "[2/4] 소스 복사 (lambda_handler.py + 공유 src/)..."
Copy-Item $handler $build
Copy-Item (Join-Path $root "src") (Join-Path $build "src") -Recurse

Write-Host "[3/4] __pycache__ 제거..."
Get-ChildItem $build -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force

Write-Host "[4/4] zip 생성..."
Compress-Archive -Path (Join-Path $build "*") -DestinationPath $zip -Force
Remove-Item $build -Recurse -Force

Write-Host ""
Write-Host "완료: $zip"
Write-Host "핸들러 설정값: lambda_handler.lambda_handler"
