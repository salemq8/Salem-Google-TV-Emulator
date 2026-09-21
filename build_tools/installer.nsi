Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "x64.nsh"

!define APP "Salem Google TV Emulator"
!define REGKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\SalemGoogleTVEmulator"
Name "${APP} v1.0"
OutFile "${STAGE}\dist\Setup.exe"
InstallDir "$LOCALAPPDATA\Programs\${APP}"
RequestExecutionLevel user
ManifestSupportedOS all
SetCompressor /SOLID lzma
Icon "${ROOT}\assets\salem_google_tv_emulator.ico"
UninstallIcon "${ROOT}\assets\salem_google_tv_emulator.ico"
VIProductVersion "1.0.0.0"
VIAddVersionKey /LANG=1033 "ProductName" "${APP}"
VIAddVersionKey /LANG=1033 "ProductVersion" "1.0"
VIAddVersionKey /LANG=1033 "FileVersion" "1.0"
VIAddVersionKey /LANG=1033 "CompanyName" "Salem"
VIAddVersionKey /LANG=1033 "FileDescription" "${APP} Setup"
VIAddVersionKey /LANG=1033 "LegalCopyright" "Copyright Salem"

Var TestMode
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP}\${APP}.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Open ${APP}"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Function .onInit
  SetShellVarContext current
  ${GetParameters} $0
  ClearErrors
  ${GetOptions} $0 "/TEST" $1
  ${IfNot} ${Errors}
    StrCpy $TestMode "1"
    ${If} $INSTDIR == "$LOCALAPPDATA\Programs\${APP}"
      SetErrorLevel 3
      Quit
    ${EndIf}
  ${EndIf}
  ; Native checks run before the embedded Python helper is extracted or launched.
  System::Alloc 64
  Pop $0
  System::Call 'kernel32::GetNativeSystemInfo(p r0)'
  System::Call '*$0(&i2 .r1)'
  System::Free $0
  ${If} $1 != 9
    MessageBox MB_OK|MB_ICONSTOP "${APP} requires an x64 Windows PC. This architecture is not supported." /SD IDOK
    SetErrorLevel 2
    Quit
  ${EndIf}
  System::Alloc 284
  Pop $0
  System::Call '*$0(i 284)'
  System::Call 'ntdll::RtlGetVersion(p r0)i.r1'
  System::Call '*$0(i, i .r2, i, i .r3)'
  System::Free $0
  ${If} $1 != 0
  ${OrIf} $2 < 10
  ${OrIf} $3 < 17763
    MessageBox MB_OK|MB_ICONSTOP "${APP} requires Windows 10 build 17763 or later, or Windows 11, 64-bit. Your Windows version is not supported." /SD IDOK
    SetErrorLevel 2
    Quit
  ${EndIf}
FunctionEnd

Section "${APP} (required)" Main
  SectionIn RO
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  File "${STAGE}\dist\SetupHelper.exe"
  DetailPrint "Verifying and staging application files. Existing engine data will be preserved."
  ExecWait '"$PLUGINSDIR\SetupHelper.exe" --silent --no-shortcuts --target "$INSTDIR"' $0
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONSTOP "Installation could not finish. Close Salem and retry. Your previous installation and engine data have been preserved. Details: $LOCALAPPDATA\${APP}\logs\installer.json" /SD IDOK
    SetErrorLevel 1
    Abort
  ${EndIf}
  SetOutPath "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  ${If} $TestMode == "1"
    WriteINIStr "$INSTDIR\install-state.ini" "Install" "TestMode" "1"
  ${Else}
    SetOutPath "$INSTDIR\${APP}"
    ClearErrors
    CreateShortcut "$SMPROGRAMS\${APP}.lnk" "$INSTDIR\${APP}\${APP}.exe"
    ${If} ${Errors}
      MessageBox MB_OK|MB_ICONEXCLAMATION "Application installed, but the Start Menu shortcut could not be created. Open the EXE from $INSTDIR\${APP}." /SD IDOK
    ${EndIf}
    WriteRegStr HKCU "${REGKEY}" "DisplayName" "${APP}"
    WriteRegStr HKCU "${REGKEY}" "DisplayVersion" "1.0"
    WriteRegStr HKCU "${REGKEY}" "Publisher" "Salem"
    WriteRegStr HKCU "${REGKEY}" "InstallLocation" "$INSTDIR"
    WriteRegStr HKCU "${REGKEY}" "DisplayIcon" "$INSTDIR\${APP}\${APP}.exe,0"
    WriteRegStr HKCU "${REGKEY}" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
    WriteRegStr HKCU "${REGKEY}" "QuietUninstallString" '$\"$INSTDIR\Uninstall.exe$\" /S'
    WriteRegDWORD HKCU "${REGKEY}" "NoModify" 1
    WriteRegDWORD HKCU "${REGKEY}" "NoRepair" 1
  ${EndIf}
SectionEnd

Section /o "Desktop shortcut" Desktop
  ${If} $TestMode != "1"
    SetOutPath "$INSTDIR\${APP}"
    CreateShortcut "$DESKTOP\${APP}.lnk" "$INSTDIR\${APP}\${APP}.exe"
  ${EndIf}
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  ReadINIStr $TestMode "$INSTDIR\install-state.ini" "Install" "TestMode"
  ClearErrors
  Delete "$INSTDIR\${APP}\${APP}.exe"
  ${If} ${Errors}
    MessageBox MB_OK|MB_ICONSTOP "Close Salem before uninstalling. No application data has been removed." /SD IDOK
    SetErrorLevel 1
    Abort
  ${EndIf}
  ; Delete only this build's explicit payload files, never SDK, AVDs or settings.
  !include "${STAGE}\uninstall-files.nsh"
  ${If} $TestMode != "1"
    ReadRegStr $0 HKCU "${REGKEY}" "InstallLocation"
    ${If} $0 == $INSTDIR
      Delete "$SMPROGRAMS\${APP}.lnk"
      Delete "$DESKTOP\${APP}.lnk"
      DeleteRegKey HKCU "${REGKEY}"
    ${EndIf}
  ${EndIf}
  Delete "$INSTDIR\install-state.ini"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
SectionEnd
