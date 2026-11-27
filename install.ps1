# Understand This Video Plugin installer for Windows. Normally started by "Install Understand This Video (Windows).bat".
#   advanced: powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName Microsoft.VisualBasic
Add-Type -AssemblyName System.Windows.Forms
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$App = Join-Path $env:USERPROFILE ".video-context\app"
$Title = "Understand This Video Plugin"
New-Item -ItemType Directory -Force (Join-Path $env:USERPROFILE ".video-context") | Out-Null
Start-Transcript -Path (Join-Path $env:USERPROFILE ".video-context\install.log") -Append | Out-Null
Write-Host "== $Title installer =="
function Note($m) { [void][System.Windows.Forms.MessageBox]::Show($m, $Title) }
function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
}
try {
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
  Note "Windows needs the free 'App Installer' from the Microsoft Store first. Install it, then run this installer again."; exit 1
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
Write-Host "Installing the plugin into $App ..."
& $py.Source -m venv $App
& "$App\Scripts\python.exe" -m pip install -q --upgrade pip
& "$App\Scripts\pip.exe" install -q "$Here[all]"

$ff = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ff) { $env:Path = (Split-Path $ff.Source) + ";" + $env:Path }
$Desk = [Environment]::GetFolderPath("Desktop")
if (-not $Desk) { $Desk = Join-Path $env:USERPROFILE "Desktop" }
$VidFolder = Join-Path $Desk "Understand This Video"
New-Item -ItemType Directory -Force $VidFolder | Out-Null
Write-Host "Connecting your AI apps..."
& "$App\Scripts\python.exe" "$Here\register_mcp.py" "$App\Scripts\understand-this-video-mcp.exe"

$Key = $env:VIDEO_CONTEXT_LICENSE_KEY
if (-not $Key) { $Key = [Microsoft.VisualBasic.Interaction]::InputBox("Paste your license key (it is in your purchase email) and click OK.`nNo key yet? Click Cancel and run this installer again later.", $Title, "") }
$Result = "nokey"
if ($Key) {
  & "$App\Scripts\understand-this-video.exe" activate $Key.Trim()
  if ($LASTEXITCODE -eq 0) { $Result = "ok" } else { $Result = "badkey" }
}

# Download everything the plugin needs NOW (speech models, test run), so your first video is fast.
Write-Host ""
Write-Host "Getting everything ready so your first video is fast (one time)."
Write-Host "This downloads the speech models (about 600 MB in total) and can take several minutes on a slow connection."
& "$App\Scripts\understand-this-video.exe" --warmup
if ($LASTEXITCODE -ne 0) { Write-Host "Some downloads did not finish. The plugin will finish them the first time you use it (it will just be slower once)." }

if ($Result -eq "ok") { Note "All set! A folder called Understand This Video is now on your Desktop. Put your video in it. Then close and reopen your AI app (Claude, Cursor...) and ask: Understand my latest video"; Start-Process explorer.exe $VidFolder }
elseif ($Result -eq "badkey") { Note "The license key was not accepted. Check it and run this installer again, or email video@shipmonthly.com." }
else { Note "Installed. Run this installer again whenever you want to enter your license key." }
} catch { Note ("Something went wrong: " + $_.Exception.Message + "`nDetails: %USERPROFILE%\.video-context\install.log. Email video@shipmonthly.com for help."); exit 1 }
