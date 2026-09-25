# Compila el driver de cámara virtual UltraCam (64 y 32 bits) y deja las DLL en vcam_driver\bin.
#
#   powershell -ExecutionPolicy Bypass -File vcam_driver\build.ps1
#
# Requiere Visual Studio 2022 o Build Tools 2022 con «Desarrollo para el escritorio con C++».
param(
    [ValidateSet("Release", "Debug")]
    [string]$Config = "Release"
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

function Find-CMake {
    $cmd = Get-Command cmake -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswhere) {
        $vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
        $candidate = Join-Path $vs "Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
        if ($vs -and (Test-Path $candidate)) { return $candidate }
    }
    throw "No se encontró CMake ni Visual Studio 2022 con C++. Instala «Build Tools para Visual Studio 2022»."
}

function Copy-Replacing($src, $dst) {
    # Si un programa (Zoom, Chrome, OBS…) tiene cargada la DLL anterior, Windows no deja
    # sobrescribirla pero sí renombrarla: se aparta y se copia la nueva. Los apartados se
    # borran cuando ya nadie los usa.
    Get-ChildItem "$dst.old-*" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
    if (Test-Path $dst) {
        try { Remove-Item $dst -Force -ErrorAction Stop }
        catch { Rename-Item $dst ("$(Split-Path $dst -Leaf).old-" + (Get-Date -Format "yyyyMMddHHmmss")) }
    }
    Copy-Item $src $dst
}

$cmake = Find-CMake
$bin = Join-Path $root "bin"
New-Item -ItemType Directory -Force $bin | Out-Null

foreach ($arch in @("x64", "Win32")) {
    $build = Join-Path $root "build\$arch"
    Write-Host "==> Compilando $arch ($Config)" -ForegroundColor Cyan
    & $cmake -S $root -B $build -G "Visual Studio 17 2022" -A $arch | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "CMake no pudo configurar $arch" }
    & $cmake --build $build --config $Config --parallel | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Falló la compilación de $arch" }
    $suffix = if ($arch -eq "x64") { "64" } else { "32" }
    Copy-Replacing (Join-Path $build "$Config\ultracam-vcam$suffix.dll") (Join-Path $bin "ultracam-vcam$suffix.dll")
    # Herramienta de prueba (no se empaqueta con la app)
    New-Item -ItemType Directory -Force (Join-Path $root "tests\bin") | Out-Null
    Copy-Replacing (Join-Path $build "$Config\vcam_probe$suffix.exe") (Join-Path $root "tests\bin\vcam_probe$suffix.exe")
}
Write-Host "Listo: $bin" -ForegroundColor Green
Get-ChildItem $bin -Filter *.dll | Select-Object Name, Length | Format-Table | Out-Host
