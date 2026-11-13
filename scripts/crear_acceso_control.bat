@echo off
REM ============================================================================
REM  SDMR - Crear acceso directo del Centro de Control (Windows)
REM ============================================================================
REM  Genera "SDMR Centro de Control.lnk" en el Escritorio, apuntando a
REM  centro_control.bat. Hacé doble clic en este archivo una sola vez.
REM ============================================================================
setlocal
set "SCRIPT=%~dp0centro_control.bat"
set "LNK=%USERPROFILE%\Desktop\SDMR Centro de Control.lnk"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s = New-Object -ComObject WScript.Shell; $l = $s.CreateShortcut('%LNK%'); $l.TargetPath = '%SCRIPT%'; $l.WorkingDirectory = '%~dp0'; $l.IconLocation = '%SystemRoot%\System32\shell32.dll,18'; $l.Description = 'SDMR Centro de Control'; $l.Save()"

if errorlevel 1 (
    echo No se pudo crear el acceso directo.
) else (
    echo Acceso directo creado en: %LNK%
)
pause
endlocal
