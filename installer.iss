; Inno Setup script for Renombrador PKS 2026.
;
; Builds an installer from the PyInstaller onedir bundle produced by
; ``build.bat``.  Install with:
;
;   iscc installer.iss
;
; Requires Inno Setup 6+.  Download from https://jrsoftware.org/isinfo.php

#define AppName         "Renombrador PKS 2026"
#ifndef AppVersion
  ; build.bat la inyecta desde src/core/version.py con /DAppVersion=...
  #define AppVersion    "3.9.2"
#endif
#define AppPublisher    "AEROSCAN"
#define AppExeName      "RenombradorPKS.exe"
#define AppInternalName "RenombradorPKS"
#define SourceDir       "dist\{#AppInternalName}"

[Setup]
AppId={{8F2E9F0B-2F5A-4B3C-8A9D-8A5E7C0A1B42}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppInternalName}
DefaultGroupName={#AppName}
OutputBaseFilename=RenombradorPKS_Setup_{#AppVersion}
OutputDir=dist_installer
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExeName}
DisableProgramGroupPage=yes
WizardStyle=modern
SetupIconFile=src\assets\branding\app_icon.ico
LicenseFile=

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";   Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"
Name: "startmenuicon"; Description: "Crear acceso directo en el menú Inicio"; GroupDescription: "Accesos directos:"; Flags: checkedonce

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}";            Filename: "{app}\{#AppExeName}"; Tasks: startmenuicon
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}";      Tasks: startmenuicon
Name: "{autodesktop}\{#AppName}";      Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Ejecutar {#AppName}"; Flags: nowait postinstall skipifsilent
