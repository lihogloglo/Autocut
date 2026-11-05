; FauxRaccord-Setup.exe: installs FauxRaccord for the current user (no admin rights), then its Python and packages
; with uv, with a progress page. Start menu and desktop shortcuts with the app's icon, pinnable to the
; taskbar (same AppUserModelID as the window), an uninstaller in Settings > Apps. Installing a newer version
; over an older one keeps the environment (only what changed is downloaded). The user's settings, keys and
; models (%APPDATA%\fauxraccord, %LOCALAPPDATA%\fauxraccord) are never touched.
; It also puts the Premiere panel where Premiere looks for it, and registers the fauxraccord:// link
; the panel starts the app with.
;
; Built by .github/workflows/release.yml:  ISCC /DAppVersion=0.2.0 /DUvExe=path\to\uv.exe installer\FauxRaccord.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef UvExe
  #define UvExe "uv.exe"
#endif
#define AppId "lihogloglo.fauxraccord"

[Setup]
AppId={{0bc9541d-0a05-4663-91b0-843959dc3bc2}
AppName=FauxRaccord
AppVersion={#AppVersion}
AppVerName=FauxRaccord {#AppVersion}
AppPublisher=lihogloglo
AppPublisherURL=https://github.com/lihogloglo/FauxRaccord
AppSupportURL=https://github.com/lihogloglo/FauxRaccord/issues
AppUpdatesURL=https://github.com/lihogloglo/FauxRaccord/releases
DefaultDirName={localappdata}\Programs\FauxRaccord
DefaultGroupName=FauxRaccord
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=FauxRaccord-Setup
SetupIconFile=..\src\fauxraccord\web\fauxraccord.ico
UninstallDisplayIcon={app}\src\fauxraccord\web\fauxraccord.ico
UninstallDisplayName=FauxRaccord
LicenseFile=..\LICENSE
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=no
; uv reaches its Python through a directory junction (cpython-3.12-…-none). Setup's junction mitigation is
; inherited by uv and refuses it (error 448). It protects elevated installers; this one runs as the user.
RedirectionGuard=no

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
fr.SyncTitle=Installation des composants
fr.SyncText=Python et les bibliothèques de FauxRaccord (environ 2 Go la première fois, quelques minutes ; bien plus rapide pour une mise à jour).
fr.SyncFailed=L'installation des composants a échoué (code %1).%n%nVérifiez la connexion internet et relancez l'installation. Le détail est dans :%n%2
fr.CloseApp=FauxRaccord est ouvert. Fermez-le, puis cliquez sur OK.
fr.Launch=Ouvrir FauxRaccord
fr.DesktopIcon=Raccourci sur le Bureau
en.SyncTitle=Installing components
en.SyncText=Python and FauxRaccord's libraries (about 2 GB the first time, a few minutes; much faster for an update).
en.SyncFailed=Installing the components failed (code %1).%n%nCheck the internet connection and run the installer again. Details are in:%n%2
en.CloseApp=FauxRaccord is open. Close it, then click OK.
en.Launch=Open FauxRaccord
en.DesktopIcon=Desktop shortcut

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"

[InstallDelete]
; sources from the previous version: replaced as a whole, so no deleted module lingers
Type: filesandordirs; Name: "{app}\src"
Type: filesandordirs; Name: "{app}\premiere"

[Files]
Source: "..\src\*"; DestDir: "{app}\src"; Excludes: "__pycache__,*.pyc"; Flags: recursesubdirs ignoreversion
Source: "..\premiere\*"; DestDir: "{app}\premiere"; Flags: recursesubdirs ignoreversion
Source: "..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\uv.lock"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\.python-version"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#UvExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\FauxRaccord"; Filename: "{app}\.venv\Scripts\fauxraccord-gui.exe"; WorkingDir: "{app}"; IconFilename: "{app}\src\fauxraccord\web\fauxraccord.ico"; AppUserModelID: "{#AppId}"
Name: "{autodesktop}\FauxRaccord"; Filename: "{app}\.venv\Scripts\fauxraccord-gui.exe"; WorkingDir: "{app}"; IconFilename: "{app}\src\fauxraccord\web\fauxraccord.ico"; AppUserModelID: "{#AppId}"; Tasks: desktopicon

[Registry]
; fauxraccord:// starts FauxRaccord: the Premiere panel uses it to open the app by itself (the app writes it too)
Root: HKCU; Subkey: "Software\Classes\fauxraccord"; ValueType: string; ValueName: ""; ValueData: "URL:FauxRaccord"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\fauxraccord"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\fauxraccord\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\.venv\Scripts\fauxraccord-gui.exe"" ""%1"""

[UninstallRun]
; the Premiere panel goes with the app (it was copied into %APPDATA%\Adobe\UXP, not under {app})
Filename: "{app}\.venv\Scripts\python.exe"; Parameters: "-m fauxraccord.setup install panel-remove"; WorkingDir: "{app}"; Flags: runhidden; RunOnceId: "RemovePanel"

[Run]
Filename: "{app}\.venv\Scripts\fauxraccord-gui.exe"; WorkingDir: "{app}"; Description: "{cm:Launch}"; Flags: nowait postinstall skipifsilent
; an update started from the window (/SILENT /relaunch=1): open it again when done
Filename: "{app}\.venv\Scripts\fauxraccord-gui.exe"; WorkingDir: "{app}"; Flags: nowait; Check: Relaunch

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\src"
Type: files; Name: "{app}\sync.log"

[Code]
var
  SyncPage: TOutputMarqueeProgressWizardPage;

function Relaunch: Boolean;
begin
  Result := ExpandConstant('{param:relaunch|0}') = '1';
end;

{ The window holds this mutex (gui.py). An update started from it closes it: give it a few seconds. }
function InitializeSetup: Boolean;
var
  i: Integer;
begin
  i := 0;
  while CheckForMutexes('{#AppId}') and (i < 30) do
  begin
    Sleep(500);
    i := i + 1;
  end;
  Result := True;
  while Result and CheckForMutexes('{#AppId}') do
    Result := MsgBox(CustomMessage('CloseApp'), mbInformation, MB_OKCANCEL) = IDOK;
end;

procedure InitializeWizard;
begin
  SyncPage := CreateOutputMarqueeProgressPage(CustomMessage('SyncTitle'), CustomMessage('SyncText'));
end;

var
  SyncLog: String;

{ each line of uv's output: on the page (the last one) and in sync.log (all of them) }
procedure SyncLine(const S: String; const Error, FirstLine: Boolean);
var
  Line: String;
begin
  Line := Trim(S);
  SaveStringToFile(SyncLog, S + #13#10, True);
  if Line <> '' then
    SyncPage.SetText(CustomMessage('SyncText'), Copy(Line, 1, 110));
  SyncPage.Animate;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
begin
  if CurStep <> ssPostInstall then
    exit;
  SyncLog := ExpandConstant('{app}\sync.log');
  DeleteFile(SyncLog);
  SyncPage.Show;
  try
    { uv brings its own Python 3.12 (never a system one), then the exact packages of uv.lock }
    if not ExecAndLogOutput(ExpandConstant('{app}\uv.exe'),
        'sync --frozen --python-preference only-managed --color never -v',
        ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, Code, @SyncLine) or (Code <> 0) then
      MsgBox(FmtMessage(CustomMessage('SyncFailed'), [IntToStr(Code), SyncLog]), mbError, MB_OK)
    else
      { the Premiere panel, copied where Premiere looks for it (no Creative Cloud needed); nothing without Premiere }
      Exec(ExpandConstant('{app}\.venv\Scripts\python.exe'), '-m fauxraccord.setup install panel',
           ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, Code);
  finally
    SyncPage.Hide;
  end;
end;
