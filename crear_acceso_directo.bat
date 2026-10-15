@echo off
REM ============================================================================
REM  SDMR - Creador de acceso directo en el Escritorio (Windows)
REM ============================================================================
REM  Genera un acceso directo "SDMR.lnk" en el Escritorio que apunta a
REM  iniciar_sdmr.bat. Hace doble clic en este archivo una sola vez.
REM ============================================================================
setlocal
set "SCRIPT=%~dp0iniciar_sdmr.bat"
set "LNK=%USERPROFILE%\Desktop\SDMR.lnk"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s = New-Object -ComObject WScript.Shell; $l = $s.CreateShortcut('%LNK%'); $l.TargetPath = '%SCRIPT%'; $l.WorkingDirectory = '%~dp0'; $l.IconLocation = '%SystemRoot%\System32\shell32.dll,14'; $l.Description = 'SDMR - Monitoreo en Red'; $l.Save()"

if errorlevel 1 (
    echo No se pudo crear el acceso directo.
) else (
    echo Acceso directo creado en: %LNK%
)
pause
endlocal
