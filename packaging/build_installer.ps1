# Compatibilidad: el build principal ahora es build.ps1 (portable por defecto).
# Este atajo genera el ZIP portable y además el instalador.
& (Join-Path $PSScriptRoot "build.ps1") -Installer
