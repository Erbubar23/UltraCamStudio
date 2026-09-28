; Instalador de UltraCam Studio (Inno Setup 6)
; Lo compila packaging\build_installer.ps1; no hace falta abrirlo a mano.

#ifndef AppVersion
  #define AppVersion "0.20.4-beta"
#endif
#define AppName "UltraCam Studio"
#define AppExe "UltraCamStudio.exe"

[Setup]
AppId={{6F1C2E4A-8B7D-4C3E-9A51-2D7E0B4F9C11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=UltraCam Studio
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Instalación por usuario: sin UAC ni permisos de administrador
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=UltraCamStudio-Setup-{#AppVersion}
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
InfoBeforeFile=LEEME_TESTERS.txt
CloseApplications=yes

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "..\dist\UltraCamStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "LEEME_TESTERS.txt"; DestDir: "{app}"; Flags: ignoreversion

[Registry]
; La app registra la cámara «UltraCam» para el usuario al abrirse; al desinstalar se quita
; (64 y 32 bits) para que no quede una cámara que apunta a una DLL borrada.
Root: HKCU64; Subkey: "Software\Classes\CLSID\{{E7D1A5EA-54D9-4644-9E4D-1FA4F637870A}"; Flags: dontcreatekey uninsdeletekey
Root: HKCU64; Subkey: "Software\Classes\CLSID\{{860BB310-5D01-11d0-BD3B-00A0C911CE86}\Instance\{{E7D1A5EA-54D9-4644-9E4D-1FA4F637870A}"; Flags: dontcreatekey uninsdeletekey
Root: HKCU32; Subkey: "Software\Classes\CLSID\{{E7D1A5EA-54D9-4644-9E4D-1FA4F637870A}"; Flags: dontcreatekey uninsdeletekey
Root: HKCU32; Subkey: "Software\Classes\CLSID\{{860BB310-5D01-11d0-BD3B-00A0C911CE86}\Instance\{{E7D1A5EA-54D9-4644-9E4D-1FA4F637870A}"; Flags: dontcreatekey uninsdeletekey

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Léeme (testers)"; Filename: "{app}\LEEME_TESTERS.txt"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir {#AppName} ahora"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Copias locales del driver de la cámara virtual (la app las registra desde aquí)
Type: filesandordirs; Name: "{localappdata}\UltraCamStudio\vcam"

[UninstallRun]
; Libera el puerto USB de teléfonos Android antes de borrar adb.exe
Filename: "{app}\bin\scrcpy\adb.exe"; Parameters: "kill-server"; Flags: runhidden skipifdoesntexist; RunOnceId: "KillAdb"
