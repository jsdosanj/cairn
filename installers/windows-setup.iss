; Inno Setup script for Cairn (formerly GhostAssetSync)
;
; Build with:
;   1. Run installers/build-windows.ps1 first so dist/cairn.exe exists.
;   2. Open this file in Inno Setup Compiler (or run ISCC.exe windows-setup.iss).
;
; Produces a Windows installer that places cairn.exe under Program Files\Cairn
; and adds that directory to the system PATH.

#define MyAppName "Cairn"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Cairn contributors"
#define MyAppExeName "cairn.exe"

[Setup]
AppId={{B7E6C2A1-4F3D-4E9B-9C2A-CA1RNCA1RN01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={commonpf}\Cairn
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
ArchitecturesInstallIn64BitMode=x64
OutputBaseFilename=cairn-windows-setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
PrivilegesRequired=admin

[Files]
; Built by installers/build-windows.ps1 into ..\dist\cairn.exe
Source: "..\dist\cairn.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\config.example.yaml"; DestDir: "{app}"; Flags: ignoreversion

[Tasks]
Name: "addtopath"; Description: "Add Cairn to the system PATH"; GroupDescription: "System integration:"

[Registry]
; Append the install dir to the system PATH when the addtopath task is selected.
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
    ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; \
    Check: NeedsAddPath('{app}'); Tasks: addtopath

[Code]
function NeedsAddPath(Param: string): Boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKLM,
    'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
    'Path', OrigPath)
  then begin
    Result := True;
    exit;
  end;
  // Only add if not already present (case-insensitive).
  Result := Pos(';' + Lowercase(ExpandConstant(Param)) + ';',
                ';' + Lowercase(OrigPath) + ';') = 0;
end;
