; Chaeksas 설치 스크립트 — Studio·PC 실행기가 함께 쓴다 (ADR-0068).
;
; **직접 iscc로 부르지 않는다** — `packaging/build.py --installer`가 앱마다 다른 값을 /D로 넘긴다:
;   AppKey      bot-ui | studio
;   AppId       고정 GUID (바꾸면 덮어쓰기가 아니라 두 번째 설치가 된다)
;   AppName     표시 이름 (한글일 수 있다 — 바로가기·제거 목록)
;   AppFileName 설치 파일 이름의 앞부분 (ASCII — `ChaeksasBotUI`)
;   AppExe      실행 파일 이름 (예: ChaeksasBotUI.exe)
;   AppDirName  설치 폴더 이름 (예: BotUI)
;   AppVersion  찍힌 판 (ADR-0067 — 0.2.0 또는 0.1.0+g<커밋>)
;   NumericVersion  파일 속성용 숫자 판 (0.2.0.0)
;   SourceDir   묶은 onedir 폴더
;   OutputDir   설치 파일을 둘 곳
;   AutostartTask  (PC 실행기만) 제거할 때 지울 작업 스케줄러 이름 — `autostart.TASK_NAME`
;   ToolUiName     (PC 실행기만) 같은 실행 파일을 `--tool-ui`로 여는 바로가기 이름 (ADR-0077 §6)
;
; 사용자별 설치다 — 관리자 권한을 묻지 않는다. 자리는 %LOCALAPPDATA%\Programs\Chaeksas\<앱>.
; 서명이 없다 — 처음 설치할 때 SmartScreen이 경고한다 (docs/04-setup.md).

#ifndef AppKey
  #error build.py가 넘긴 값이 없다 — `uv run --group build python packaging/build.py --installer`로 만든다
#endif

[Setup]
AppId={{{#AppId}}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Chaeksas
VersionInfoVersion={#NumericVersion}
VersionInfoProductVersion={#NumericVersion}
VersionInfoProductTextVersion={#AppVersion}
; 사용자별 — PC 전체 설치로 넘어가는 길도 열지 않는다 (ADR-0068 §2).
PrivilegesRequired=lowest
DefaultDirName={autopf}\Chaeksas\{#AppDirName}
; 자리를 고르게 하지 않는다 — 하나여야 덮어쓰기와 「판 올리기」가 단순하다.
DisableDirPage=yes
DefaultGroupName=Chaeksas
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename={#AppFileName}-setup-{#AppVersion}
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
; 600MB 폴더라 최대 압축은 CI에서 몇 분이 걸린다 — 빠른 쪽을 쓴다.
Compression=lzma2/fast
SolidCompression=yes
; 실행 중이면 닫고 깐다 (Restart Manager). 덮어쓸 때 옛 파일을 쥐고 있으면 깨진다.
CloseApplications=yes
RestartApplications=no
WizardStyle=modern
ShowLanguageDialog=no

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕 화면에 바로 가기 만들기"; GroupDescription: "바로 가기:"; Flags: unchecked

[InstallDelete]
; **옛 판의 파일을 먼저 지운다** (ADR-0068 §3) — onedir에서 덮어쓰기만 하면 새 판에서 빠진
; 모듈·dist-info가 남아 섞인다.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Chaeksas\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
#ifdef ToolUiName
; Tool UI는 PC 실행기 실행 파일이 `--tool-ui`로 뜬 것이다 — 따로 깔지 않는다 (ADR-0077 §6).
Name: "{autoprograms}\Chaeksas\{#ToolUiName}"; Filename: "{app}\{#AppExe}"; Parameters: "--tool-ui"
#endif

[Run]
Filename: "{app}\{#AppExe}"; Description: "{#AppName} 실행"; Flags: nowait postinstall skipifsilent

#ifdef AutostartTask
[UninstallRun]
; 자동 시작은 앱이 건다(BUI-03). 제거할 때 지우기만 한다 — 없으면 schtasks가 실패하고 그것으로 됐다.
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""{#AutostartTask}"" /F"; Flags: runhidden; RunOnceId: "RemoveAutostart"
#endif
