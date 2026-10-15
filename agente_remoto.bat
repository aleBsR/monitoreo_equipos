@echo off
REM ============================================================================
REM  SDMR - Lanzador de Agente Remoto (Windows)
REM ============================================================================
REM  Arranca un Agente de Monitoreo en ESTE equipo apuntando al Servidor Central
REM  que corre en otro equipo de la red local. Pensado para la prueba del TP con
REM  2 o mas dispositivos en red.
REM
REM  Uso:
REM      agente_remoto.bat <IP_SERVIDOR> [ID_NODO] [PUERTO_UDP] [PUERTO_CMD]
REM
REM  Ejemplos:
REM      agente_remoto.bat 192.168.1.50
REM      agente_remoto.bat 192.168.1.50 NODO_02
REM      agente_remoto.bat 192.168.1.50 NODO_02 5000 5002
REM ============================================================================
setlocal
cd /d "%~dp0"

if "%~1"=="" goto :uso
if "%~1"=="-h" goto :uso
if "%~1"=="--help" goto :uso

set "IP_SERVIDOR=%~1"
set "ID_NODO=%~2"
if "%ID_NODO%"=="" set "ID_NODO=%COMPUTERNAME%"
set "PUERTO_UDP=%~3"
if "%PUERTO_UDP%"=="" set "PUERTO_UDP=5000"
set "PUERTO_CMD=%~4"
if "%PUERTO_CMD%"=="" set "PUERTO_CMD=5002"

REM Elegir interprete: se prefiere el lanzador 'py' (Python Launcher)
where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
) else (
    set "PY=python"
)

%PY% --version >nul 2>nul
if errorlevel 1 (
    echo.
    echo ERROR: No se encontro Python 3.
    echo Instalalo desde https://www.python.org/downloads/ y marca la opcion
    echo "Add Python to PATH" durante la instalacion.
    echo.
    pause
    exit /b 1
)

echo =================================================================
echo  SDMR - Agente Remoto
echo =================================================================
echo  Servidor central : %IP_SERVIDOR% (UDP %PUERTO_UDP%)
echo  Nodo             : %ID_NODO%
echo  Canal EXEC local : TCP %PUERTO_CMD%
echo =================================================================
echo  Asegurate de que el firewall del servidor permita UDP %PUERTO_UDP% y
echo  TCP 5001, y que ESTE equipo permita TCP %PUERTO_CMD% (para EXEC).
echo -----------------------------------------------------------------

%PY% -u agent\agent.py "%ID_NODO%" "%IP_SERVIDOR%" "%PUERTO_UDP%" "%PUERTO_CMD%"

if errorlevel 1 (
    echo.
    echo El agente finalizo con error.
    pause
)
endlocal
exit /b 0

:uso
echo Uso: agente_remoto.bat ^<IP_SERVIDOR^> [ID_NODO] [PUERTO_UDP] [PUERTO_CMD]
echo.
echo   IP_SERVIDOR  IP del equipo donde corre server/server.py (obligatorio)
echo   ID_NODO      Identificador del nodo (por defecto: nombre de este equipo)
echo   PUERTO_UDP   Puerto de telemetria del servidor (por defecto: 5000)
echo   PUERTO_CMD   Puerto TCP de comandos EXEC de este agente (por defecto: 5002)
echo.
echo Ejemplo: agente_remoto.bat 192.168.1.50 NODO_02
endlocal
exit /b 1
