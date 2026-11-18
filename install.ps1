# Understand This Video For Me AI Plugin installer for Windows. Run in PowerShell:
#   powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$App = Join-Path $env:USERPROFILE ".video-context\app"
Write-Host "== Understand This Video For Me AI Plugin installer =="

function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
}
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
  Write-Host "winget not found. Install 'App Installer' from the Microsoft Store, then re-run."; exit 1
}
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
  Write-Host "Installing ffmpeg..."
  winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
  Refresh-Path
}
$py = Get-Command py -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python -ErrorAction SilentlyContinue }
if (-not $py -or ($py.Source -like "*WindowsApps*")) {
  Write-Host "Installing Python..."
  winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
  Refresh-Path
  $py = Get-Command py -ErrorAction SilentlyContinue
  if (-not $py) { $py = Get-Command python }
}
Write-Host "Installing Understand This Video For Me AI Plugin into $App ..."
& $py.Source -m venv $App
& "$App\Scripts\python.exe" -m pip install -q --upgrade pip
& "$App\Scripts\pip.exe" install -q "$Here[all]"

# make sure the GUI apps can find ffmpeg
$ff = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ff) { $env:Path = (Split-Path $ff.Source) + ";" + $env:Path }
Write-Host "Registering with Claude Desktop and Cursor..."
& "$App\Scripts\python.exe" "$Here\register_mcp.py" "$App\Scripts\understand-this-video-mcp.exe"

$Key = $env:VIDEO_CONTEXT_LICENSE_KEY
if (-not $Key) { $Key = Read-Host "Paste your license key (from your purchase email)" }
if ($Key) { & "$App\Scripts\understand-this-video.exe" activate $Key }
else { Write-Host "Later, activate with: $App\Scripts\understand-this-video.exe activate YOUR-KEY" }
Write-Host ""
Write-Host "Done! Restart Claude Desktop / Cursor, then ask: 'Watch C:\path\video.mp4 and summarize it'."
