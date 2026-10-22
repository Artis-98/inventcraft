; Inno Setup script for InventCraft.  Driven by tools/release.py, which
; passes the version in, so the version here always matches the build.
;
; This installs per user, into %LOCALAPPDATA%\Programs\InventCraft, and that
; is a deliberate choice rather than a lazy one.  A per-machine install into
; Program Files needs an administrator prompt to install and another one
; every time it updates, and the updater cannot write there at all from a
; normal user account.  Per user, InventCraft can replace its own files
; quietly, which is the whole point of the update channel.
;
; InventCraft was called DATUM until 0.3.0.  The AppId is the one DATUM
; had, so this installs over an existing DATUM, into the folder it is
; already in, and replaces it in the list of installed programs rather
; than appearing next to it.  DATUM.exe is shipped as well as
; InventCraft.exe, the same program under its old name, because a copy
; updating itself from 0.2.x restarts DATUM.exe when it is done.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

; Paths in an .iss resolve against the folder holding the script, not the
; working directory, so everything outside tools/ goes through Root.
#define Root AddBackslash(SourcePath) + ".."

#define MyAppName "InventCraft"
#define MyAppPublisher "SIA IITEG"
#define MyAppURL "https://iiteg.com"
#define MyAppExeName "InventCraft.exe"

[Setup]
AppId={{8C4E2F6A-9D1B-4E57-B3A2-7F0C5D8E1A94}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
VersionInfoVersion={#MyAppVersion}

; Per user, no elevation.  See the note at the top.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={localappdata}\Programs\{#MyAppName}
DisableProgramGroupPage=yes
DefaultGroupName={#MyAppName}

OutputBaseFilename=InventCraft-{#MyAppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes

; The uninstaller lives beside the application so a clean uninstall
; really does take the folder with it.
UninstallDisplayName={#MyAppName} {#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile={#Root}\tools\inventcraft.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; \
    GroupDescription: "Shortcuts:"
Name: "associate"; Description: \
    "Open InventCraft files (.icpart, .icasm, .icdraw, .iccam, and DATUM's .pdat, .adat, .ddat, .cdat) with {#MyAppName}"; \
    GroupDescription: "File types:"

[Files]
Source: "{#Root}\dist\InventCraft\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; DATUM's own shortcuts, which would otherwise stay on the Start menu and
; the desktop under the old name
Type: files; Name: "{autoprograms}\DATUM\DATUM.lnk"
Type: dirifempty; Name: "{autoprograms}\DATUM"
Type: files; Name: "{autoprograms}\DATUM.lnk"
Type: files; Name: "{autodesktop}\DATUM.lnk"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    Tasks: desktopicon

[Registry]
; Per user associations, matching the per user install.  HKA resolves to
; HKCU here because PrivilegesRequired is lowest.  The ProgIDs keep DATUM's
; names, so a file DATUM associated is simply pointed at InventCraft.
Root: HKA; Subkey: "Software\Classes\.icpart"; ValueType: string; \
    ValueName: ""; ValueData: "IITEG.DATUM.Part"; \
    Flags: uninsdeletevalue; Tasks: associate
Root: HKA; Subkey: "Software\Classes\.icasm"; ValueType: string; \
    ValueName: ""; ValueData: "IITEG.DATUM.Assembly"; \
    Flags: uninsdeletevalue; Tasks: associate
Root: HKA; Subkey: "Software\Classes\.iccam"; ValueType: string; \
    ValueName: ""; ValueData: "IITEG.DATUM.Cam"; \
    Flags: uninsdeletevalue; Tasks: associate
Root: HKA; Subkey: "Software\Classes\.icdraw"; ValueType: string; \
    ValueName: ""; ValueData: "IITEG.DATUM.Drawing"; \
    Flags: uninsdeletevalue; Tasks: associate
Root: HKA; Subkey: "Software\Classes\.pdat"; ValueType: string; \
    ValueName: ""; ValueData: "IITEG.DATUM.Part"; \
    Flags: uninsdeletevalue; Tasks: associate
Root: HKA; Subkey: "Software\Classes\.adat"; ValueType: string; \
    ValueName: ""; ValueData: "IITEG.DATUM.Assembly"; \
    Flags: uninsdeletevalue; Tasks: associate
Root: HKA; Subkey: "Software\Classes\.cdat"; ValueType: string; \
    ValueName: ""; ValueData: "IITEG.DATUM.Cam"; \
    Flags: uninsdeletevalue; Tasks: associate
Root: HKA; Subkey: "Software\Classes\.ddat"; ValueType: string; \
    ValueName: ""; ValueData: "IITEG.DATUM.Drawing"; \
    Flags: uninsdeletevalue; Tasks: associate

Root: HKA; Subkey: "Software\Classes\IITEG.DATUM.Part"; ValueType: string; \
    ValueName: ""; ValueData: "InventCraft Part"; Flags: uninsdeletekey; \
    Tasks: associate
Root: HKA; Subkey: "Software\Classes\IITEG.DATUM.Assembly"; \
    ValueType: string; ValueName: ""; ValueData: "InventCraft Assembly"; \
    Flags: uninsdeletekey; Tasks: associate
Root: HKA; Subkey: "Software\Classes\IITEG.DATUM.Cam"; ValueType: string; \
    ValueName: ""; ValueData: "InventCraft CAM Sheet"; Flags: uninsdeletekey; \
    Tasks: associate
Root: HKA; Subkey: "Software\Classes\IITEG.DATUM.Drawing"; \
    ValueType: string; ValueName: ""; ValueData: "InventCraft Drawing"; \
    Flags: uninsdeletekey; Tasks: associate

Root: HKA; Subkey: "Software\Classes\IITEG.DATUM.Part\DefaultIcon"; \
    ValueType: string; ValueName: ""; \
    ValueData: """{app}\{#MyAppExeName}"",0"; Tasks: associate
Root: HKA; Subkey: "Software\Classes\IITEG.DATUM.Assembly\DefaultIcon"; \
    ValueType: string; ValueName: ""; \
    ValueData: """{app}\{#MyAppExeName}"",0"; Tasks: associate
Root: HKA; Subkey: "Software\Classes\IITEG.DATUM.Cam\DefaultIcon"; \
    ValueType: string; ValueName: ""; \
    ValueData: """{app}\{#MyAppExeName}"",0"; Tasks: associate
Root: HKA; Subkey: "Software\Classes\IITEG.DATUM.Drawing\DefaultIcon"; \
    ValueType: string; ValueName: ""; \
    ValueData: """{app}\{#MyAppExeName}"",0"; Tasks: associate

Root: HKA; Subkey: "Software\Classes\IITEG.DATUM.Part\shell\open\command"; \
    ValueType: string; ValueName: ""; \
    ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: associate
Root: HKA; \
    Subkey: "Software\Classes\IITEG.DATUM.Assembly\shell\open\command"; \
    ValueType: string; ValueName: ""; \
    ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: associate
Root: HKA; Subkey: "Software\Classes\IITEG.DATUM.Cam\shell\open\command"; \
    ValueType: string; ValueName: ""; \
    ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: associate
Root: HKA; \
    Subkey: "Software\Classes\IITEG.DATUM.Drawing\shell\open\command"; \
    ValueType: string; ValueName: ""; \
    ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: associate

[Run]
Filename: "{app}\{#MyAppExeName}"; \
    Description: "Start {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The updater's staging folder is created after install, so Inno does not
; know about it and would otherwise leave it behind.
Type: filesandordirs; Name: "{app}\.staging"
