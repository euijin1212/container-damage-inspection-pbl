# 보고서 자동화 Lambda(report_generator) 배포 패키지(zip) 생성 스크립트 (Windows PowerShell)
#
# 사용법:
#   .\build_report_lambda.ps1
# 결과:
#   report_lambda_deploy.zip  (handler.py + 공유 src/ + fpdf2 포함)
#
# 참고:
#   - boto3 는 Lambda 런타임에 기본 포함이라 넣지 않는다.
#   - fpdf2 는 Pillow(네이티브) 를 의존하므로, Windows 에서 빌드해도 Lambda(Linux)
#     에서 돌아가도록 Linux 휠(manylinux)을 명시적으로 내려받아 번들한다.
#   - Lambda 런타임/아키텍처에 맞춰 아래 파라미터를 조정한다.
#   - PDF 한글 렌더링이 필요하면 한글 TTF 를 src\fonts\ 에 넣거나
#     Lambda 환경변수 REPORT_FONT_PATH 로 지정한다.

param(
    [string]$PyVersion = "3.12",                 # Lambda 파이썬 런타임
    [string]$Platform  = "manylinux2014_x86_64"  # arm64 면 manylinux2014_aarch64
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$build = Join-Path $root "build_report"
$zip = Join-Path $root "report_lambda_deploy.zip"
$handler = Join-Path $root "lambda\report_generator\handler.py"

Write-Host "[1/5] 이전 산출물 정리..."
if (Test-Path $build) { Remove-Item $build -Recurse -Force }
if (Test-Path $zip) { Remove-Item $zip -Force }
New-Item -ItemType Directory -Path $build | Out-Null

Write-Host "[2/5] 소스 복사 (handler.py + 공유 src/)..."
Copy-Item $handler $build
Copy-Item (Join-Path $root "src") (Join-Path $build "src") -Recurse

Write-Host "[3/5] 의존성 설치 (fpdf2 + Linux 휠: Pillow 등)..."
python -m pip install --quiet --target $build `
    --platform $Platform `
    --implementation cp `
    --python-version $PyVersion `
    --only-binary=:all: `
    "fpdf2>=2.7.0"

Write-Host "[4/5] __pycache__ 제거..."
Get-ChildItem $build -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force

Write-Host "[5/5] zip 생성..."
Compress-Archive -Path (Join-Path $build "*") -DestinationPath $zip -Force
Remove-Item $build -Recurse -Force

Write-Host ""
Write-Host "완료: $zip"
Write-Host "핸들러 설정값: handler.lambda_handler"
Write-Host "런타임: python$PyVersion / 아키텍처 휠: $Platform"
Write-Host "트리거: DynamoDB Streams (container-inspection 테이블)"
