@echo off
REM Double-click installer for Windows. If SmartScreen warns: More info > Run anyway.
set VER=1.2.1
echo Understand This Video Plugin: installing. Please wait, this takes a few minutes.
echo A box will ask for your license key near the end.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=Join-Path $env:USERPROFILE '.video-context\src'; New-Item -ItemType Directory -Force $d | Out-Null; Remove-Item -Recurse -Force (Join-Path $d 'video-context-ai') -ErrorAction SilentlyContinue; [Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest ('https://github.com/africaappstudio-max/video-context-ai-download/releases/download/v'+$env:VER+'/video-context-ai.zip') -OutFile (Join-Path $d 'plugin.zip'); Expand-Archive -Force (Join-Path $d 'plugin.zip') $d; & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $d 'video-context-ai\install.ps1')"
echo.
echo You can close this window.
pause
