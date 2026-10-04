# Construye UltraCam Studio para Windows como app PORTABLE (no hay que instalar nada).
#
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1              -> ZIP portable
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -Installer   -> además, instalador
#
# Resultado: dist\UltraCamStudio-Portable-<version>.zip (descomprimir y abrir UltraCamStudio.exe).
# Pasos: entorno virtual con dependencias -> icono -> descarga de scrcpy y FFmpeg
#        -> PyInstaller (sin necesidad de Python en la PC destino) -> ZIP portable [-> Inno Setup].
# La app guarda su configuración en la carpeta "data" junto al .exe.

param([switch]$Installer)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root   = Split-Path -Parent $PSScriptRoot
$Build  = Join-Path $Root "build"
$Vendor = Join-Path $Build "vendor"
$Venv   = Join-Path $Build ".venv"
$Dist   = Join-Path $Root "dist"
$AppDir = Join-Path $Dist "UltraCamStudio"

$Version = (Select-String -Path (Join-Path $Root "gui.py") -Pattern 'APP_VERSION = "([^"]+)"').Matches[0].Groups[1].Value
Write-Host "== UltraCam Studio $Version ==" -ForegroundColor Yellow
New-Item -ItemType Directory -Force $Build, $Vendor | Out-Null

# 1. Entorno virtual limpio con solo lo necesario
Write-Host "[1/5] Preparando entorno de Python..."
if (-not (Test-Path "$Venv\Scripts\python.exe")) { py -3 -m venv $Venv }
$Py = "$Venv\Scripts\python.exe"
& $Py -m pip install --upgrade pip --quiet --disable-pip-version-check
& $Py -m pip install -r (Join-Path $Root "requirements.txt") pyinstaller pillow --quiet --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw "Falló la instalación de dependencias" }

# 2. Icono
Write-Host "[2/5] Generando icono..."
& $Py (Join-Path $PSScriptRoot "make_icon.py")

# 3. Binarios externos (se descargan una vez y quedan en caché)
function Get-ReleaseAsset($repo, $pattern) {
    $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/$repo/releases/latest" -Headers @{ "User-Agent" = "UltraCamBuild" }
    $asset = $rel.assets | Where-Object { $_.name -match $pattern } | Select-Object -First 1
    if (-not $asset) { throw "No se encontró un archivo que coincida con '$pattern' en $repo" }
    return $asset
}
function Get-Vendor($name, $repo, $pattern) {
    $dir = Join-Path $Vendor $name
    if (Test-Path (Join-Path $dir ".ok")) { return $dir }
    $asset = Get-ReleaseAsset $repo $pattern
    $zip = Join-Path $Vendor $asset.name
    Write-Host "      Descargando $($asset.name) ($([math]::Round($asset.size / 1MB)) MB)..."
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -UseBasicParsing
    $tmp = Join-Path $Vendor "$name-extract"
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
    Expand-Archive -Path $zip -DestinationPath $tmp
    if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
    New-Item -ItemType Directory -Force $dir | Out-Null
    return @{ Dir = $dir; Tmp = $tmp; Zip = $zip }
}

Write-Host "[3/5] Obteniendo scrcpy, FFmpeg y MediaMTX..."
$sc = Get-Vendor "scrcpy" "Genymobile/scrcpy" '^scrcpy-win64-v[\d.]+\.zip$'
if ($sc -is [hashtable]) {
    $src = Get-ChildItem $sc.Tmp -Directory | Select-Object -First 1
    Get-ChildItem $src.FullName -File | Where-Object { $_.Extension -notin ".bat", ".vbs" } |
        Copy-Item -Destination $sc.Dir
    Remove-Item -Recurse -Force $sc.Tmp; Remove-Item -Force $sc.Zip
    New-Item -ItemType File (Join-Path $sc.Dir ".ok") | Out-Null
}
# Build "shared" de FFmpeg: ffmpeg.exe y ffplay.exe comparten DLLs (mucho más liviano que el estático)
$ff = Get-Vendor "ffmpeg" "BtbN/FFmpeg-Builds" '^ffmpeg-n8\.\d+-latest-win64-gpl-shared-8\.\d+\.zip$'
if ($ff -is [hashtable]) {
    $bin = Get-ChildItem $ff.Tmp -Recurse -Directory -Filter bin | Select-Object -First 1
    Get-ChildItem $bin.FullName -File | Where-Object { $_.Name -in "ffmpeg.exe", "ffplay.exe" -or $_.Extension -eq ".dll" } |
        Copy-Item -Destination $ff.Dir
    $lic = Get-ChildItem $ff.Tmp -Recurse -File -Filter LICENSE.txt | Select-Object -First 1
    if ($lic) { Copy-Item $lic.FullName (Join-Path $ff.Dir "LICENSE.txt") }
    Remove-Item -Recurse -Force $ff.Tmp; Remove-Item -Force $ff.Zip
    New-Item -ItemType File (Join-Path $ff.Dir ".ok") | Out-Null
}
# MediaMTX (MIT): reparte la transmisión a cada plataforma con un solo codificador
$mx = Get-Vendor "mediamtx" "bluenviron/mediamtx" '^mediamtx_v[\d.]+_windows_amd64\.zip$'
if ($mx -is [hashtable]) {
    Get-ChildItem $mx.Tmp -File | Where-Object { $_.Name -in "mediamtx.exe", "LICENSE" } | Copy-Item -Destination $mx.Dir
    Remove-Item -Recurse -Force $mx.Tmp; Remove-Item -Force $mx.Zip
    New-Item -ItemType File (Join-Path $mx.Dir ".ok") | Out-Null
}

# Driver de la cámara virtual «UltraCam» (C++): requiere Build Tools 2022 con C++
Write-Host "      Compilando el driver de la cámara virtual..."
& (Join-Path $Root "vcam_driver\build.ps1")

# 4. Empaquetado de la app (no requiere Python en la PC de destino)
Write-Host "[4/5] Empaquetando la app con PyInstaller..."
if (Test-Path $AppDir) { Remove-Item -Recurse -Force $AppDir }
& $Py -m PyInstaller --noconfirm --clean --windowed `
    --name UltraCamStudio `
    --icon (Join-Path $Root "assets\app.ico") `
    --add-data "$(Join-Path $Root 'assets');assets" `
    --collect-data customtkinter `
    --collect-all pyaudiowpatch `
    --collect-all sounddevice `
    --collect-all _sounddevice_data `
    --collect-all pedalboard `
    --collect-all obsws_python `
    --hidden-import audio_server `
    --distpath $Dist --workpath (Join-Path $Build "pyi") --specpath $Build `
    (Join-Path $Root "main.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falló" }

# scrcpy y FFmpeg en carpetas separadas: cada uno carga sus propias DLLs
New-Item -ItemType Directory -Force (Join-Path $AppDir "bin") | Out-Null
Copy-Item -Recurse (Join-Path $Vendor "scrcpy") (Join-Path $AppDir "bin\scrcpy")
Copy-Item -Recurse (Join-Path $Vendor "ffmpeg") (Join-Path $AppDir "bin\ffmpeg")
Copy-Item -Recurse (Join-Path $Vendor "mediamtx") (Join-Path $AppDir "bin\mediamtx")
Get-ChildItem (Join-Path $AppDir "bin") -Recurse -Filter ".ok" | Remove-Item -Force
# La app registra la cámara al abrirse con la ruta de estas DLL (por usuario, sin administrador)
$VcamDir = Join-Path $AppDir "vcam_driver"
New-Item -ItemType Directory -Force $VcamDir | Out-Null
Copy-Item (Join-Path $Root "vcam_driver\bin\ultracam-vcam*.dll") $VcamDir
Copy-Item (Join-Path $Root "vcam_driver\third_party\LICENSE-softcam.txt") $VcamDir

# 5. Paquete portable
Write-Host "[5/5] Creando el paquete portable..."
Copy-Item (Join-Path $PSScriptRoot "LEEME_TESTERS.txt") (Join-Path $AppDir "LEEME.txt")
# GPLv3: el paquete lleva la licencia y los avisos de terceros
Copy-Item (Join-Path $Root "LICENSE") (Join-Path $AppDir "LICENSE.txt")
Copy-Item (Join-Path $Root "THIRD_PARTY_NOTICES.md") $AppDir
$Zip = Join-Path $Dist "UltraCamStudio-Portable-$Version.zip"
if (Test-Path $Zip) { Remove-Item -Force $Zip }
Compress-Archive -Path $AppDir -DestinationPath $Zip -CompressionLevel Optimal
$ZipMB = [math]::Round((Get-Item $Zip).Length / 1MB, 1)
Write-Host ""
Write-Host "Listo (portable): $Zip ($ZipMB MB)" -ForegroundColor Green
Write-Host "  Descomprime la carpeta donde quieras (Escritorio, Documentos, memoria USB) y abre UltraCamStudio.exe"

if (-not $Installer) { return }

# 6. Instalador (opcional)
Write-Host "[6/6] Creando el instalador con Inno Setup..."
$Iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) {
    Write-Host "      Inno Setup no está instalado; instalándolo con winget..."
    winget install --id JRSoftware.InnoSetup -e --silent --scope user --accept-package-agreements --accept-source-agreements | Out-Null
    $Iscc = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $Iscc) { throw "No se pudo instalar Inno Setup. Instálalo desde https://jrsoftware.org/isdl.php y vuelve a ejecutar." }
}
& $Iscc "/DAppVersion=$Version" /Q (Join-Path $PSScriptRoot "installer.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup falló" }

$Setup = Join-Path $Dist "UltraCamStudio-Setup-$Version.exe"
$SizeMB = [math]::Round((Get-Item $Setup).Length / 1MB, 1)
Write-Host ""
Write-Host "Listo: $Setup ($SizeMB MB)" -ForegroundColor Green
