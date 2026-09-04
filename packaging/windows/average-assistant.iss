#ifndef AppVersion
  #error AppVersion must be supplied by the build workflow
#endif

[Setup]
AppId={{C6DBF7E5-8D19-4F56-B443-77B0DB93A689}
AppName=Average Assistant
AppVersion={#AppVersion}
AppPublisher=Erik Boettcher (TheIlluminate92)
AppPublisherURL=https://github.com/TheIlluminate92/usbc-average-lookup
AppSupportURL=https://github.com/TheIlluminate92/usbc-average-lookup/issues
AppUpdatesURL=https://github.com/TheIlluminate92/usbc-average-lookup/releases/latest
DefaultDirName={localappdata}\Programs\Average Assistant
DisableDirPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\..\release
OutputBaseFilename=Average-Assistant-{#AppVersion}-Setup
UninstallDisplayIcon={app}\USBC-Average-Lookup.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Tasks]
Name: desktopicon; Description: "Create a &desktop shortcut"; Flags: unchecked

[Files]
Source: "..\..\dist\USBC-Average-Lookup\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Average Assistant"; Filename: "{app}\USBC-Average-Lookup.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Average Assistant"; Filename: "{app}\USBC-Average-Lookup.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\USBC-Average-Lookup.exe"; Description: "Open Average Assistant"; Flags: nowait postinstall skipifsilent

; Bowler data lives in {localappdata}\Average Assistant, outside {app}.
; Never add this data directory to Files, InstallDelete, or UninstallDelete.
