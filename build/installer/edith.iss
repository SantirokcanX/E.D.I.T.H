; EDITH-Setup.exe (Fase 15.4) — instalador por usuario, sin permisos de administrador.
; Se compila con build\build_setup.ps1 (paso 5), que pasa la versión del archivo VERSION:
;   ISCC.exe /DAppVersion=0.0.13 build\installer\edith.iss
; Parámetros útiles del instalador:
;   /NOCLOSEEDITH=1   no cerrar una EDITH abierta (pruebas: la EDITH del código usa los mismos nombres)
;   /VERYSILENT /SUPPRESSMSGBOXES /DIR="..." /NOICONS /TASKS=""   instalación desatendida

#define AppName "EDITH"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\EDITH"
#endif

[Setup]
AppId={{8C1F4C9E-5D6B-4E1A-9A35-ED17E0A0E417}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=EDITH
AppComments=Asistente de IA local: voz, Obsidian, WhatsApp y control de la laptop.
VersionInfoVersion={#AppVersion}.0
VersionInfoDescription=Instalador de EDITH
DefaultDirName={userpf}\EDITH
DefaultGroupName=EDITH
DisableProgramGroupPage=yes
AllowNoIcons=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\..\dist
OutputBaseFilename=EDITH-Setup-{#AppVersion}
SetupIconFile=..\..\desktop\assets\edith-app.ico
UninstallDisplayIcon={app}\EDITH.exe
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; EDITH se cierra con su propio evento (ver [Code]); el Restart Manager no hace falta
CloseApplications=no

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Types]
Name: "full"; Description: "Completa (con WhatsApp)"
Name: "compact"; Description: "Solo EDITH"
Name: "custom"; Description: "Personalizada"; Flags: iscustom

[Components]
Name: "main"; Description: "EDITH (app de escritorio)"; Types: full compact custom; Flags: fixed
Name: "whatsapp"; Description: "WhatsApp: háblale a EDITH desde el celular (unos 100 MB)"; Types: full

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el Escritorio"; GroupDescription: "Accesos directos:"
Name: "startup"; Description: "Iniciar EDITH con Windows (oculta en la bandeja, junto al reloj)"; GroupDescription: "Inicio:"; Flags: unchecked
Name: "ollama"; Description: "Descargar e instalar Ollama (motor de la IA local, necesario; unos 1 GB)"; GroupDescription: "Inteligencia artificial:"; Check: not OllamaInstalled

[Files]
Source: "{#SourceDir}\EDITH.exe"; DestDir: "{app}"; Components: main; Flags: ignoreversion
Source: "{#SourceDir}\_internal\*"; DestDir: "{app}\_internal"; Components: main; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceDir}\edith-whatsapp.exe"; DestDir: "{app}"; Components: whatsapp; Flags: ignoreversion skipifsourcedoesntexist

[InstallDelete]
; Al actualizar, la carpeta _internal se reemplaza entera (no quedan librerías de la versión anterior)
Type: filesandordirs; Name: "{app}\_internal"

[UninstallDelete]
Type: files; Name: "{app}\.no-cerrar-edith"

[Icons]
; En su carpeta del menú Inicio ({group}): /NOICONS la omite y no se pisa el acceso de la EDITH del código
Name: "{group}\EDITH"; Filename: "{app}\EDITH.exe"; WorkingDir: "{app}"; Comment: "Asistente de IA local"
Name: "{userdesktop}\EDITH"; Filename: "{app}\EDITH.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
; Mismo valor que escribe Ajustes › Iniciar con Windows
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "EDITH"; ValueData: """{app}\EDITH.exe"" --tray"; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{app}\EDITH.exe"; Description: "Abrir EDITH ahora"; Flags: nowait postinstall skipifsilent

[Code]
const
  SYNCHRONIZE = $00100000;
  EVENT_MODIFY_STATE = $0002;
  RUN_KEY = 'Software\Microsoft\Windows\CurrentVersion\Run';

var
  DownloadPage: TDownloadWizardPage;

function OpenEvent(dwDesiredAccess: Cardinal; bInheritHandle: Boolean; lpName: string): THandle;
  external 'OpenEventW@kernel32.dll stdcall';
function OpenMutex(dwDesiredAccess: Cardinal; bInheritHandle: Boolean; lpName: string): THandle;
  external 'OpenMutexW@kernel32.dll stdcall';
function SetEvent(hEvent: THandle): Boolean;
  external 'SetEvent@kernel32.dll stdcall';
function CloseHandle(hObject: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';

// /NOCLOSEEDITH=1 (pruebas): no se cierra la EDITH abierta. Queda una marca en la carpeta del programa
// para que el desinstalador tampoco la cierre, aunque no reciba el parámetro. Una instalación normal no la tiene.
function KeepEdithOpen: Boolean;
begin
  Result := (ExpandConstant('{param:NOCLOSEEDITH|0}') = '1')
    or FileExists(ExpandConstant('{app}\.no-cerrar-edith'));
end;

function OllamaInstalled: Boolean;
begin
  Result := FileExists(ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe'))
    or FileExists(ExpandConstant('{commonpf64}\Ollama\ollama.exe'));
end;

function EdithRunning: Boolean;
var
  H: THandle;
begin
  H := OpenMutex(SYNCHRONIZE, False, 'Local\EDITH_Desktop_Instance');
  Result := H <> 0;
  if Result then
    CloseHandle(H);
end;

{ Pide a EDITH que se cierre (el mismo evento que usa «Salir» del icono) y espera hasta 20 s }
procedure CloseEdith;
var
  H: THandle;
  I: Integer;
begin
  if KeepEdithOpen or not EdithRunning then
    Exit;
  H := OpenEvent(EVENT_MODIFY_STATE, False, 'Local\EDITH_Desktop_Quit');
  if H <> 0 then
  begin
    SetEvent(H);
    CloseHandle(H);
  end;
  for I := 1 to 40 do
  begin
    if not EdithRunning then
      Exit;
    Sleep(500);
  end;
end;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage(SetupMessage(msgWizardPreparing), 'Descargando Ollama desde ollama.com…', nil);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpReady) and WizardIsTaskSelected('ollama') then
  begin
    DownloadPage.Clear;
    DownloadPage.Add('https://ollama.com/download/OllamaSetup.exe', 'OllamaSetup.exe', '');
    DownloadPage.Show;
    try
      try
        DownloadPage.Download;
      except
        if not DownloadPage.AbortedByUser then
          SuppressibleMsgBox('No pude descargar Ollama (' + GetExceptionMessage + ').' + #13#10 +
            'EDITH se instala igual; luego descárgalo de ollama.com.', mbError, MB_OK, IDOK);
      end;
    finally
      DownloadPage.Hide;
    end;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  CloseEdith;
  if EdithRunning and not KeepEdithOpen then
    Result := 'EDITH sigue abierta. Ciérrala desde el icono junto al reloj (clic derecho › Salir) y vuelve a intentarlo.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
begin
  if (CurStep = ssPostInstall) and (ExpandConstant('{param:NOCLOSEEDITH|0}') = '1') then
    SaveStringToFile(ExpandConstant('{app}\.no-cerrar-edith'), '1', False);
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('ollama')
     and FileExists(ExpandConstant('{tmp}\OllamaSetup.exe')) then
    Exec(ExpandConstant('{tmp}\OllamaSetup.exe'), '', '', SW_SHOW, ewWaitUntilTerminated, Code);
end;

function InitializeUninstall: Boolean;
begin
  Result := True;
  CloseEdith;
  if EdithRunning and not KeepEdithOpen then
  begin
    MsgBox('EDITH sigue abierta. Ciérrala desde el icono junto al reloj (clic derecho › Salir) y vuelve a intentarlo.',
      mbError, MB_OK);
    Result := False;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Value, Data: String;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  { «Iniciar con Windows» activado desde Ajustes: también se quita si apunta a esta instalación }
  if RegQueryStringValue(HKCU, RUN_KEY, 'EDITH', Value) and
     (Pos(Lowercase(ExpandConstant('{app}')), Lowercase(Value)) > 0) then
    RegDeleteValue(HKCU, RUN_KEY, 'EDITH');
  { Tus datos solo se borran si lo pides; en una desinstalación silenciosa, nunca }
  Data := ExpandConstant('{localappdata}\EDITH');
  if (not UninstallSilent) and DirExists(Data) then
    if MsgBox('¿Borrar también tus conversaciones, memoria y ajustes de EDITH?' + #13#10 + #13#10 + Data + #13#10 + #13#10 +
              'Si eliges «No», se conservan para cuando vuelvas a instalarla.',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(Data, True, True, True);
end;
