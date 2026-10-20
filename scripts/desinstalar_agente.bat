@echo off
REM ============================================================================
REM  SDMR - Desinstalador del Agente (Windows)
REM ============================================================================
REM  Detiene el agente que este corriendo, quita el acceso directo de la
REM  carpeta de Inicio y elimina la regla de firewall "SDMR EXEC".
REM  No borra el codigo del proyecto ni agent\config.ini.
REM ============================================================================
setlocal
cd /d "%~dp0.."
set "RAIZ=%CD%"
set "LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\SDMR Agente.lnk"

echo =================================================================
echo  SDMR - Desinstalacion del Agente
echo =================================================================

REM ----------------------- Detener el agente -------------------------------
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*agent.py*' -and $_.CommandLine -like '*--silent*' }; if ($p) { $p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } }; if ($p) { 'Agente detenido.' } else { 'No hay agentes corriendo en este equipo.' }"

REM ---------------------- Acceso directo de Inicio -------------------------
if exist "%LNK%" (
    del /q "%LNK%"
    echo Acceso directo de Inicio eliminado.
) else (
    echo No habia acceso directo en la carpeta de Inicio.
)

REM ------------------------- Regla de firewall -----------------------------
net session >nul 2>nul
if errorlevel 1 (
    echo Sin derechos de administrador: se omite el borrado de la regla.
    echo Para quitarla a mano: netsh advfirewall firewall delete rule name="SDMR EXEC"
) else (
    netsh advfirewall firewall delete rule name="SDMR EXEC" >nul 2>nul
    echo Regla de firewall "SDMR EXEC" eliminada.
)

echo.
echo Listo. El agente no arrancara mas al iniciar sesion.
echo Para volver a instalarlo: scripts\instalar_agente.bat
echo.
pause
endlocal
exit /b 0
