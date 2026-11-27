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
function Note($m) {
  if ($m -notmatch '(\r?\n){2}') {
    $m = [regex]::Replace($m, '(?<=[.?!])[ \t]+(?=[A-Z])', "`r`n`r`n")
  }
  $m = $m -replace '(\r?\n){2,}', "`r`n`r`n"
  [void][System.Windows.Forms.MessageBox]::Show($m, $Title)
}
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
if (-not $Key) { $Key = [Microsoft.VisualBasic.Interaction]::InputBox("Paste your license key (it is in your purchase email) and click OK.`r`n`r`nThe plugin will not work without your license key.`r`n`r`nNo key yet? Click Cancel, then run this installer again when you have it.", $Title, "") }
$Result = "nokey"
if ($Key) {
  & "$App\Scripts\understand-this-video.exe" activate $Key.Trim()
  if ($LASTEXITCODE -eq 0) { $Result = "ok" } else { $Result = "badkey" }
}

# Download speech models if needed. Re-runs skip the download when they are already on this computer.
Write-Host ""
Write-Host "Checking the speech models..."
& "$App\Scripts\understand-this-video.exe" --warmup
if ($LASTEXITCODE -ne 0) { Write-Host "Some downloads did not finish."; Write-Host ""; Write-Host "The plugin will finish them the first time you use it (it will just be slower once)." }

if ($Result -eq "ok") { Note "All set!`r`n`r`nA folder called Understand This Video is now on your Desktop.`r`n`r`nPut your video in it.`r`n`r`nThen close and reopen your AI app (Claude, Cursor...) and ask: Understand my latest video"; Start-Process explorer.exe $VidFolder }
elseif ($Result -eq "badkey") { Note "The license key was not accepted.`r`n`r`nThe plugin will not work without a valid key.`r`n`r`nCheck the key in your purchase email and run this installer again, or email video@shipmonthly.com." }
else { Note "The plugin is installed, but it is not activated yet because you skipped the license key.`r`n`r`nThe plugin will not work without it.`r`n`r`nRun this installer again and paste the key from your purchase email.`r`n`r`nThen close and reopen your AI app.`r`n`r`nNo key yet? Get one at https://understandvideo.shipmonthly.com" }
} catch { Note ("Something went wrong: " + $_.Exception.Message + "`r`n`r`nDetails: %USERPROFILE%\.video-context\install.log.`r`n`r`nEmail video@shipmonthly.com for help."); exit 1 }
