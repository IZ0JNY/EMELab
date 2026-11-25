; EME Assistant installer (internal name EMELab: same AppId, folder and data, so it upgrades 0.1.x) (Inno Setup 6). Built by windows\build.ps1 from build\EMELab.
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
AppId={{93F88144-2420-4C57-8078-2265FAC0A472}
AppName=EME Assistant
AppVersion={#MyAppVersion}
AppVerName=EME Assistant {#MyAppVersion}
AppPublisher=IZ0JNY
AppPublisherURL=https://github.com/IZ0JNY/EMELab
AppSupportURL=https://github.com/IZ0JNY/EMELab/issues
DefaultDirName={localappdata}\Programs\EMELab
DefaultGroupName=EME Assistant
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=EME-Assistant-Setup-{#MyAppVersion}
SetupIconFile=emelab.ico
UninstallDisplayIcon={app}\emelab.ico
UninstallDisplayName=EME Assistant {#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
CloseApplications=yes
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany=IZ0JNY
VersionInfoDescription=EME Assistant setup - EME planning, measurements and coaching
VersionInfoProductName=EME Assistant
VersionInfoProductVersion={#MyAppVersion}
VersionInfoCopyright=(c) Ivan De Cesaris IZ0JNY - GPLv3
LicenseFile=..\LICENSE

ShowLanguageDialog=yes
UsePreviousLanguage=no

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
italian.AppComment=Misure, pianificazione e log EME da 10 a 134 GHz
english.AppComment=EME measurements, planning and log from 10 to 134 GHz
italian.InBrowser=nel browser
english.InBrowser=in the browser

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Registry]
; language chosen in the installer = default language of the app (changeable in the app sidebar)
Root: HKCU; Subkey: "Software\EMELab"; ValueType: string; ValueName: "Language"; ValueData: "{language}"; Flags: uninsdeletekey

[InstallDelete]
Type: filesandordirs; Name: "{app}\app"
; clean upgrade: no packages left over from the previous version
Type: filesandordirs; Name: "{app}\python"
; Start-menu entry "in the browser" of a previous install in the other language (recreated below)
Type: files; Name: "{autoprograms}\EMELab (nel browser).lnk"
Type: files; Name: "{autoprograms}\EMELab (in the browser).lnk"
Type: files; Name: "{autoprograms}\EME Assistant (nel browser).lnk"
Type: files; Name: "{autoprograms}\EME Assistant (in the browser).lnk"
; shortcuts of 0.1.0/0.1.1, when the program was called EMELab
Type: files; Name: "{autoprograms}\EMELab.lnk"
Type: files; Name: "{autodesktop}\EMELab.lnk"

[Files]
Source: "..\build\EMELab\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\EME Assistant"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m emelab.desktop"; WorkingDir: "{app}\app"; IconFilename: "{app}\emelab.ico"; AppUserModelID: "IZ0JNY.EMELab"; Comment: "{cm:AppComment}"
Name: "{autoprograms}\EME Assistant ({cm:InBrowser})"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m emelab.desktop --browser"; WorkingDir: "{app}\app"; IconFilename: "{app}\emelab.ico"; AppUserModelID: "IZ0JNY.EMELab"
Name: "{autodesktop}\EME Assistant"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m emelab.desktop"; WorkingDir: "{app}\app"; IconFilename: "{app}\emelab.ico"; AppUserModelID: "IZ0JNY.EMELab"; Tasks: desktopicon

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: "-m emelab.desktop"; WorkingDir: "{app}\app"; Description: "{cm:LaunchProgram,EME Assistant}"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\app"

