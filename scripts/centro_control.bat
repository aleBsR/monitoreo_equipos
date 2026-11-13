@echo off
REM ============================================================================
REM  SDMR - Centro de Control (Windows)
REM ============================================================================
REM  Arranca el panel local de control y lo abre en el navegador. Desde el panel
REM  se prende/apaga todo el stack sin usar la terminal.
REM
REM  Uso:  centro_control.bat  [puerto]   (por defecto 7070)
REM ============================================================================
setlocal
set "RAIZ=%~dp0.."
set "PUERTO=%~1"
if "%PUERTO%"=="" set "PUERTO=7070"

REM Preferir pythonw (sin ventana de consola) si está disponible.
where pythonw >nul 2>&1 && (set "PY=pythonw") || (set "PY=python")

start "" %PY% "%RAIZ%\scripts\centro_control.py" %PUERTO%
timeout /t 1 /nobreak >nul
start "" "http://127.0.0.1:%PUERTO%"
endlocal
