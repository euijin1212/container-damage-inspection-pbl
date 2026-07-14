# Build report_generator Lambda deploy zip (Windows PowerShell)
#
# Usage:
#   .\build_report_lambda.ps1
# Output:
#   report_lambda_deploy.zip  (handler.py + src/ + fpdf2)

param(
    [string]$PyVersion = "3.12",
    [string]$Platform  = "manylinux2014_x86_64"
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$build = Join-Path $root "build_report"
$zip = Join-Path $root "report_lambda_deploy.zip"
$handler = Join-Path $root "lambda\report_generator\handler.py"

Write-Host "[1/5] cleaning..."
if (Test-Path $build) { Remove-Item $build -Recurse -Force }
if (Test-Path $zip) { Remove-Item $zip -Force }
New-Item -ItemType Directory -Path $build | Out-Null

Write-Host "[2/5] copy handler.py + src/..."
Copy-Item $handler $build
Copy-Item (Join-Path $root "src") (Join-Path $build "src") -Recurse

Write-Host "[3/5] install deps (fpdf2 Linux wheel)..."
python -m pip install --quiet --target $build `
    --platform $Platform `
    --implementation cp `
    --python-version $PyVersion `
    --only-binary=:all: `
    "fpdf2>=2.7.0"

Write-Host "[4/5] remove __pycache__..."
Get-ChildItem $build -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force

Write-Host "[5/5] zip..."
Compress-Archive -Path (Join-Path $build "*") -DestinationPath $zip -Force
Remove-Item $build -Recurse -Force

Write-Host ""
Write-Host "done: $zip"
Write-Host "handler: handler.lambda_handler"
Write-Host "runtime: python$PyVersion / wheel: $Platform"
Write-Host "trigger: DynamoDB Streams (review_status -> DONE)"
