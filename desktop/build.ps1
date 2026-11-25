# 构建 Windows 单文件录音客户端
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m pip install -r requirements.txt
python -m pip install "pyinstaller>=6.0"

python -m PyInstaller `
  --noconfirm --clean --onefile --windowed `
  --name MeetingMemoryRecorder `
  --icon "assets/app.ico" `
  --version-file "version_info.txt" `
  --add-data "assets;assets" `
  --collect-all sounddevice `
  --collect-all customtkinter `
  --hidden-import pystray._win32 `
  main.py

$target = Join-Path $PSScriptRoot "dist\MeetingMemoryRecorder-v1.1.0.exe"
Copy-Item "dist\MeetingMemoryRecorder.exe" $target -Force
Write-Host "构建完成：$target"
