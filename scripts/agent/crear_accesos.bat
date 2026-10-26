@echo off
setlocal
set "SCRIPT=%~dp0lanzar_gui.bat"
set "LNK=%USERPROFILE%\Desktop\SDMR Control Agente.lnk"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s = New-Object -ComObject WScript.Shell; $l = $s.CreateShortcut('%LNK%'); $l.TargetPath = '%SCRIPT%'; $l.WorkingDirectory = '%~dp0'; $l.IconLocation = '%SystemRoot%\System32\shell32.dll,14'; $l.Description = 'SDMR - Control del Agente'; $l.WindowStyle = 7; $l.Save()"
if errorlevel 1 ( echo No se pudo crear el acceso directo. ) else ( echo Acceso directo creado en: %LNK% )
pause
endlocal
