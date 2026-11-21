# 内网离线安装（Windows）。在解压后的离线包目录内执行：
#   $env:APP_DIR="D:\meeting-memory"; .\install.ps1
$ErrorActionPreference = "Stop"

$BundleDir = $PSScriptRoot
$AppDir = if ($env:APP_DIR) { $env:APP_DIR } else { "$env:SystemDrive\meeting-memory" }
$Python = if ($env:PYTHON) { $env:PYTHON } else { "python" }

if (-not (Test-Path (Join-Path $BundleDir "wheels"))) {
    throw "缺少 wheels\ 目录，离线包不完整"
}
if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) {
    throw "未找到 $Python，请先安装 Python 3.10"
}

Write-Host "安装到：$AppDir"
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null

foreach ($item in @("app", "config", "deploy", "requirements.txt", "requirements-asr.txt", ".env.example")) {
    $dst = Join-Path $AppDir $item
    if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
    Copy-Item -Recurse -Force (Join-Path $BundleDir $item) $dst
}
if (Test-Path (Join-Path $BundleDir "models")) {
    New-Item -ItemType Directory -Force (Join-Path $AppDir "models") | Out-Null
    Copy-Item -Recurse -Force (Join-Path $BundleDir "models\*") (Join-Path $AppDir "models")
}
if (Test-Path (Join-Path $BundleDir "tools\ffmpeg")) {
    New-Item -ItemType Directory -Force (Join-Path $AppDir "tools") | Out-Null
    Copy-Item -Recurse -Force (Join-Path $BundleDir "tools\*") (Join-Path $AppDir "tools")
    $env:PATH = "$AppDir\tools\ffmpeg\bin;$env:PATH"
}

& $Python -m venv "$AppDir\.venv"
& "$AppDir\.venv\Scripts\python.exe" -m pip install --no-index `
    --find-links "$BundleDir\wheels" `
    -r "$AppDir\requirements.txt" -r "$AppDir\requirements-asr.txt"

if (-not (Test-Path (Join-Path $AppDir ".env"))) {
    Copy-Item (Join-Path $AppDir ".env.example") (Join-Path $AppDir ".env")
}
foreach ($d in @("data", "site", "logs")) {
    New-Item -ItemType Directory -Force (Join-Path $AppDir $d) | Out-Null
}

Write-Host @"

安装完成。后续步骤：
1. 编辑 $AppDir\.env（至少设置 APP_PASSWORD、COOKIE_SECRET、ASR_BACKEND、LLM_*）
2. 前台试运行：
   cd $AppDir
   .\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --env-file .env --host 127.0.0.1 --port 8000 --workers 1
3. FFmpeg 路径：$AppDir\tools\ffmpeg\bin（未打包时需自行安装并加入 PATH）
"@
