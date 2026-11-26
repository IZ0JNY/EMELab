<#
  Builds EMELab for Windows:
    build\EMELab\            portable folder (embedded Python + packages + app)
    dist\EMELab-<ver>-portable.zip
    dist\EMELab-Setup-<ver>.exe   (if Inno Setup is installed)

  Requirements: Windows 10/11 x64, a regular Python 3.x x64 on PATH (same minor version as -PyVersion),
  internet access. Usage (PowerShell):  .\windows\build.ps1 [-Version 0.3.0] [-PyVersion 3.13.9]
#>
param(
  [string]$Version = "",
  [string]$PyVersion = ""
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root  = Split-Path $PSScriptRoot -Parent
$build = Join-Path $root "build\EMELab"
$dist  = Join-Path $root "dist"

if (-not $Version) {
  $Version = (Select-String -Path "$root\pyproject.toml" -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value
}
if (-not $PyVersion) { $PyVersion = (python -c "import platform; print(platform.python_version())").Trim() }
$tag = ($PyVersion.Split(".")[0..1] -join "")
Write-Host "EMELab $Version  -  Python $PyVersion (embedded)"

if (Test-Path $build) { Remove-Item -Recurse -Force $build }
New-Item -ItemType Directory -Force $build, $dist | Out-Null

# 1. embedded Python
$zip = Join-Path $env:TEMP "python-$PyVersion-embed-amd64.zip"
if (-not (Test-Path $zip)) {
  Invoke-WebRequest "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-embed-amd64.zip" -OutFile $zip
}
Expand-Archive $zip -DestinationPath "$build\python"
# search path: stdlib zip, site-packages (with .pth processing) and the app folder
Set-Content -Encoding ascii "$build\python\python$tag._pth" "python$tag.zip`r`n.`r`nLib\site-packages`r`n..\app`r`nimport site`r`n"

# 2. packages (installed by a regular Python of the same version into the embedded site-packages)
python -m pip install --upgrade pip
python -m pip install --target "$build\python\Lib\site-packages" --no-warn-script-location `
  -r "$root\requirements-desktop.txt" pip setuptools
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# 3. the app
New-Item -ItemType Directory -Force "$build\app" | Out-Null
Copy-Item -Recurse "$root\emelab" "$build\app\emelab"
Copy-Item -Recurse "$root\.streamlit" "$build\app\.streamlit"
Copy-Item -Recurse "$root\docs" "$build\app\docs"
Copy-Item "$root\emelab_main.py", "$root\README.md", "$root\LICENSE" "$build\app\"
Copy-Item "$root\LICENSE" "$build\LICENSE.txt"
Copy-Item "$root\windows\emelab.ico" "$build\"
Get-ChildItem -Recurse -Directory -Filter "__pycache__" "$build\app" | Remove-Item -Recurse -Force
# Q65 Lab: the experimental decoder (WSJT-X Q65 code, GPLv3), built by the "decoder" job; its sources go with it
$q65 = Join-Path $root "build\q65lab\q65lab.exe"
if (Test-Path $q65) {
  New-Item -ItemType Directory -Force "$build\q65lab" | Out-Null
  Copy-Item $q65 "$build\q65lab\"
  Copy-Item "$root\decoder\q65lab\*" "$build\q65lab\"
} else {
  Write-Warning "q65lab.exe non trovato: Q65 Lab funzionerà solo con un decoder indicato a mano."
}

# 4. launchers. The Python interpreters are used exactly as published by python.org, with the Python
# Software Foundation's digital signature intact (a modified copy is what antivirus heuristics flag). The
# EMELab icon comes from the shortcuts (and from the window, set at run time).
Set-Content -Encoding ascii "$build\EMELab.bat" "@start `"`" `"%~dp0python\pythonw.exe`" -m emelab.desktop %*`r`n"
Set-Content -Encoding ascii "$build\EMELab (browser).bat" "@start `"`" `"%~dp0python\pythonw.exe`" -m emelab.desktop --browser`r`n"
Set-Content -Encoding utf8 "$build\LEGGIMI.txt" @"
EMELab $Version - Laboratorio di misure e pianificazione EME (10-134 GHz)
Avvio: doppio clic su EMELab.bat (finestra propria) oppure "EMELab (browser).bat".
I tuoi dati (stazione, misure, QSO, impostazioni) restano in %APPDATA%\EMELab su questo PC.
Progetto: https://github.com/IZ0JNY/EMELab
"@

# 5. precompile and self-test with the embedded interpreter
& "$build\python\python.exe" -m compileall -q "$build\app\emelab" | Out-Null
& "$build\python\python.exe" -m emelab.desktop --selftest
if ($LASTEXITCODE -ne 0) { throw "self-test failed" }

# 6. portable zip
$portable = Join-Path $dist "EMELab-$Version-portable.zip"
if (Test-Path $portable) { Remove-Item $portable }
Compress-Archive -Path $build -DestinationPath $portable -CompressionLevel Optimal

# 7. installer
$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
  foreach ($p in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
                   "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) { if (Test-Path $p) { $iscc = $p } }
}
if ($iscc) {
  & $iscc "/DMyAppVersion=$Version" "$root\windows\emelab.iss"
  if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
} else {
  Write-Warning "Inno Setup non trovato: creato solo lo zip portatile."
}
# 8. SHA-256 checksums of what is published (users can check the download: Get-FileHash <file>)
$sums = Get-ChildItem $dist -File | Where-Object { $_.Name -like "EMELab-*" } | ForEach-Object {
  "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.Name }
Set-Content -Encoding ascii (Join-Path $dist "SHA256SUMS.txt") $sums
Get-ChildItem $dist | Format-Table Name, Length
