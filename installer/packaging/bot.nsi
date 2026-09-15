; Instalador de Windows. Se compila desde Linux con makensis (ver build_win.sh).
;
; Instala en %LOCALAPPDATA%\Programs\Bot y no pide UAC: los archivos del
; programa son del usuario, no del sistema. Con eso el .exe corre igual con o
; sin permisos de administrador, que es lo que hace que se pueda repartir.
;
; Lo que instala es el PROGRAMA. La instalación de datos —la carpeta con
; boot.env, data/ y workspace/— la crea después el wizard, y el desinstalador
; no la toca: son datos del usuario, no del programa.

Unicode true
ManifestDPIAware true

!define NOMBRE    "Bot"
!define PUBLISHER "Operaciones y Mejoras"
!define CLAVE_REG "Software\Microsoft\Windows\CurrentVersion\Uninstall\Bot"

Name "${NOMBRE}"
OutFile "${SALIDA}"
InstallDir "$LOCALAPPDATA\Programs\Bot"
InstallDirRegKey HKCU "Software\Bot" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
BrandingText "${NOMBRE} ${VERSION}"

!include "MUI2.nsh"

!define MUI_ABORTWARNING
; Con una función y no con MUI_FINISHPAGE_RUN_PARAMETERS: el macro arma un
; Exec de dos argumentos y NSIS sólo acepta uno.
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION LanzarAsistente
!define MUI_FINISHPAGE_RUN_TEXT "Configurar Bot ahora"

!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Spanish"

Function LanzarAsistente
  ; SetOutPath para que el wizard arranque parado en la instalación.
  SetOutPath "$INSTDIR"
  Exec '"$INSTDIR\runtime\python.exe" "$INSTDIR\installer\instalar.py"'
FunctionEnd

Section "Programa" SEC_PRINCIPAL
  SectionIn RO
  SetOutPath "$INSTDIR"
  File /r "${CARGA}\*.*"

  CreateDirectory "$SMPROGRAMS\Bot"
  CreateShortCut "$SMPROGRAMS\Bot\Configurar Bot.lnk" \
    "$INSTDIR\runtime\python.exe" '"$INSTDIR\installer\instalar.py"' \
    "$INSTDIR\runtime\python.exe" 0
  ; Abre la última instalación que anotó el wizard (webapp/ubicacion.py). Con
  ; pythonw.exe para que no quede una consola abierta al lado del navegador:
  ; el servidor queda como ícono en la bandeja (webapp/bandeja.py), y desde
  ; ahí se abre, se reinicia y se cierra. --red: accesible desde otras PCs de
  ; la red local; la primera vez Windows pregunta por el firewall.
  CreateShortCut "$SMPROGRAMS\Bot\Abrir Bot.lnk" \
    "$INSTDIR\runtime\pythonw.exe" '-m webapp --red' \
    "$INSTDIR\runtime\python.exe" 0 SW_SHOWNORMAL "" "Abrir Bot en el navegador"

  WriteRegStr HKCU "Software\Bot" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Bot" "Version" "${VERSION}"

  ; Para que aparezca en Aplicaciones y características como cualquier programa.
  WriteRegStr   HKCU "${CLAVE_REG}" "DisplayName"     "${NOMBRE}"
  WriteRegStr   HKCU "${CLAVE_REG}" "DisplayVersion"  "${VERSION}"
  WriteRegStr   HKCU "${CLAVE_REG}" "Publisher"       "${PUBLISHER}"
  WriteRegStr   HKCU "${CLAVE_REG}" "InstallLocation" "$INSTDIR"
  WriteRegStr   HKCU "${CLAVE_REG}" "UninstallString" '"$INSTDIR\Desinstalar.exe"'
  WriteRegStr   HKCU "${CLAVE_REG}" "DisplayIcon"     "$INSTDIR\runtime\python.exe"
  WriteRegDWORD HKCU "${CLAVE_REG}" "NoModify" 1
  WriteRegDWORD HKCU "${CLAVE_REG}" "NoRepair" 1

  WriteUninstaller "$INSTDIR\Desinstalar.exe"
SectionEnd

Section "Uninstall"
  ; Sólo el programa. La carpeta de datos que creó el wizard —con la base, la
  ; llave y el espacio de trabajo— queda donde está: es del usuario, y borrarla
  ; en silencio se llevaría puesta la única llave que no se puede recuperar.
  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\backend"
  ; El núcleo anterior a la última actualización (Config → Actualizaciones).
  RMDir /r "$INSTDIR\backend.anterior"
  Delete "$INSTDIR\core-release.json"
  Delete "$INSTDIR\core-release.anterior.json"
  RMDir /r "$INSTDIR\installer"
  RMDir /r "$INSTDIR\webapp"
  Delete "$INSTDIR\LEEME.txt"
  Delete "$INSTDIR\Desinstalar.exe"
  RMDir "$INSTDIR"

  Delete "$SMPROGRAMS\Bot\Configurar Bot.lnk"
  Delete "$SMPROGRAMS\Bot\Abrir Bot.lnk"
  RMDir  "$SMPROGRAMS\Bot"

  DeleteRegKey HKCU "${CLAVE_REG}"
  DeleteRegKey HKCU "Software\Bot"
SectionEnd
