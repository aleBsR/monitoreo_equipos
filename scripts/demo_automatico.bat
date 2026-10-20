@echo off
REM ============================================================================
REM  SDMR - Demo de arranque automatico (Windows, sin terminal visible)
REM  Levanta el servidor y N agentes en ventanas ocultas. Util para mostrar el
REM  proyecto funcionando de punta a punta sin abrir varias consolas.
REM
REM  Uso:
REM      demo_automatico.bat [N_AGENTES] [IP_SERVIDOR]
REM  Por defecto: 3 agentes, IP servidor 127.0.0.1
REM ============================================================================
setlocal
cd /d "%~dp0.."
set "RAIZ=%CD%"
set "N=%~1"
if "%N%"=="" set "N=3"
set "IP=%~2"
if "%IP%"=="" set "IP=127.0.0.1"

where py >nul 2>nul
if %errorlevel%==0 ( set "PY=py -3" ) else ( set "PY=python" )

%PY% --version >nul 2>nul
if errorlevel 1 (
    echo ERROR: no se encontro Python 3.
    pause
    exit /b 1
)

for /f "delims=" %%I in ('%PY% -c "import sys;print(sys.executable)"') do set "PYEXE=%%I"
set "PYW=%PYEXE:python.exe=pythonw.exe%"
if /I "%PYW%"=="%PYEXE%" set "PYW="

set "SRV=%RAIZ%\server\server.py"
set "AGT=%RAIZ%\agent\agent.py"
set "UDP=5000"
set "TCP=5001"
set "CMD0=5002"

echo =================================================================
echo  SDMR - Demo automatica (sin terminal)
echo =================================================================
echo  Servidor : %IP%  (UDP %UDP% / TCP %TCP%)
echo  Agentes  : %N%
echo =================================================================

REM --- Servidor central (oculto) ---
if exist "%PYW%" (
    start "" "%PYW%" "%SRV%" %UDP% %TCP%
) else (
    start "SDMR Servidor" /min "%PYEXE%" -u "%SRV%" %UDP% %TCP%
)
echo [1] Servidor central iniciado (oculto).
ping -n 3 127.0.0.1 >nul

REM --- Agentes (ocultos, cada uno con su canal EXEC) ---
for /L %%i in (1,1,%N%) do (
    set /a "CMDP=!CMD0! + %%i - 1"
    setlocal enabledelayedexpansion
    set "NODO=NODO_%%i"
    set "CMDP=!CMDP!"
    if exist "%PYW%" (
        start "" "%PYW%" "%AGT%" !NODO! %IP% %UDP% !CMDP! --silent
    ) else (
        start "SDMR !NODO!" /min "%PYEXE%" -u "%AGT%" !NODO! %IP% %UDP% !CMDP! --silent
    )
    endlocal
)
echo [2] %N% agentes iniciados (ocultos).

echo.
echo Abri el dashboard del administrador con:
echo     python client\gui_monitor.py
echo y conectate a %IP% (TCP %TCP%).
echo.
echo Para detener todo: scripts\detener_demo.bat
echo =================================================================
endlocal
exit /b 0
