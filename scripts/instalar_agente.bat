@echo off
REM ============================================================================
REM  SDMR - Instalador del Agente en este equipo (Windows)
REM ============================================================================
REM  Deja el Agente de Monitoreo corriendo SIN TERMINAL, oculto, al iniciar
REM  sesion. El equipo aparece solo en el dashboard del administrador.
REM
REM  Uso:
REM      instalar_agente.bat [IP_SERVIDOR] [ID_NODO] [PUERTO_UDP] [PUERTO_CMD]
REM
REM  Ejemplos:
REM      instalar_agente.bat                       IP via broadcast (automatico)
REM      instalar_agente.bat 192.168.1.50          IP fija escrita en config.ini
REM      instalar_agente.bat 192.168.1.50 LAPTOP-JUAN
REM
REM  Que hace:
REM    1. Verifica Python 3.
REM    2. Escribe agent\config.ini (si se pasa la IP o si aun no existe).
REM    3. Crea un acceso directo en la carpeta de Inicio (arranque oculto).
REM    4. Abre la regla de firewall del canal de comandos (si hay administrador).
REM    5. Arranca el agente AHORA mismo, sin ventana.
REM
REM  Para quitarlo: scripts\desinstalar_agente.bat
REM ============================================================================
setlocal
cd /d "%~dp0.."
set "RAIZ=%CD%"

set "IP_SERVIDOR=%~1"
set "ID_NODO=%~2"
set "PUERTO_UDP=%~3"
set "PUERTO_CMD=%~4"
if "%PUERTO_UDP%"=="" set "PUERTO_UDP=5000"
if "%PUERTO_CMD%"=="" set "PUERTO_CMD=5002"

echo =================================================================
echo  SDMR - Instalacion del Agente ^(arranque automatico^)
echo =================================================================

REM ---------------------------- Interprete ---------------------------------
where py >nul 2>nul
if %errorlevel%==0 ( set "PY=py -3" ) else ( set "PY=python" )

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

for /f "delims=" %%I in ('%PY% -c "import sys;print(sys.executable)"') do set "PYEXE=%%I"
set "PYW=%PYEXE:python.exe=pythonw.exe%"
REM Si la sustitucion no cambio nada (distinta capitalizacion), no hay pythonw
if /I "%PYW%"=="%PYEXE%" set "PYW="
set "AGENTE=%RAIZ%\agent\agent.py"
set "CONFIG=%RAIZ%\agent\config.ini"
set "LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\SDMR Agente.lnk"

if not exist "%AGENTE%" (
    echo ERROR: no existe "%AGENTE%".
    echo Este instalador debe estar dentro de la carpeta scripts\ del proyecto SDMR.
    pause
    exit /b 1
)

REM ------------------------- agent\config.ini ------------------------------
if not "%IP_SERVIDOR%"=="" (
    call :escribir_config
    echo [2/5] config.ini escrito con ip_servidor=%IP_SERVIDOR%
    goto :config_listo
)
if exist "%CONFIG%" (
    echo [2/5] Se conserva el config.ini existente: "%CONFIG%"
    goto :config_listo
)
call :escribir_config
echo [2/5] config.ini creado SIN ip_servidor: el agente descubrira al
echo       Servidor Central solo, por broadcast ^(SRVREQ -^> SRVINFO^).
:config_listo

REM --------------------- Acceso directo de Inicio --------------------------
REM La carpeta de Inicio NO requiere administrador y arranca el agente apenas
REM el usuario inicia sesion. pythonw.exe = sin ventana de consola.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$w = New-Object -ComObject WScript.Shell; $l = $w.CreateShortcut($env:LNK); $l.TargetPath = $env:PYW; $l.Arguments = [char]34 + $env:AGENTE + [char]34 + ' --silent'; $l.WorkingDirectory = $env:RAIZ; $l.Description = 'SDMR - Agente de monitoreo (oculto)'; $l.WindowStyle = 7; $l.Save()"
if exist "%LNK%" (
    echo [3/5] Acceso directo creado en la carpeta de Inicio:
    echo       %LNK%
) else (
    echo [3/5] AVISO: no se pudo crear el acceso directo de Inicio.
)

REM -------------------------- Regla de firewall ----------------------------
REM Solo hace falta para el EXEC remoto; la telemetria UDP saliente funciona
REM aunque el firewall del cliente este activo.
net session >nul 2>nul
if errorlevel 1 (
    echo [4/5] Sin derechos de administrador: se omite la regla de firewall.
    echo       La telemetria llegara igual; solo el EXEC remoto podria fallar.
    echo       Para agregarla, abri una terminal como administrador y ejecuta:
    echo       netsh advfirewall firewall add rule name="SDMR EXEC" dir=in action=allow protocol=TCP localport=%PUERTO_CMD%
) else (
    netsh advfirewall firewall show rule name="SDMR EXEC" >nul 2>nul
    if errorlevel 1 (
        netsh advfirewall firewall add rule name="SDMR EXEC" dir=in action=allow protocol=TCP localport=%PUERTO_CMD% >nul
        if errorlevel 1 (
            echo [4/5] AVISO: no se pudo crear la regla de firewall.
        ) else (
            echo [4/5] Regla de firewall creada para el canal EXEC ^(TCP %PUERTO_CMD%^).
        )
    ) else (
        echo [4/5] La regla "SDMR EXEC" ya existe: se deja como esta.
    )
)

REM -------------------------- Arranque inmediato ---------------------------
if exist "%PYW%" (
    start "" "%PYW%" "%AGENTE%" --silent
    echo [5/5] Agente arrancado en segundo plano ^(sin ventana^).
) else (
    start "SDMR Agente" /min "%PYEXE%" -u "%AGENTE%" --silent
    echo [5/5] Agente arrancado minimizado ^(no se encontro pythonw.exe^).
)

echo.
echo =================================================================
echo  INSTALACION TERMINADA
echo   - Arranca solo al iniciar sesion ^(oculto, sin terminal^).
echo   - Log del agente: %RAIZ%\agent\agente.log
echo   - El equipo aparecera en la pestana "Nodos" del dashboard.
echo.
echo  En el equipo del administrador:
echo       python client\gui_monitor.py
echo  y conectate al Servidor Central. Si el agente no tiene IP escrita,
echo  la descubre solo por broadcast.
echo =================================================================
echo.
pause
endlocal
exit /b 0

REM ---------------------------------------------------------------------------
:escribir_config
REM Genera agent\config.ini con los valores recibidos (IP vacia = descubrimiento)
> "%CONFIG%" echo [nodo]
if "%ID_NODO%"=="" (>> "%CONFIG%" echo id_nodo=) else (>> "%CONFIG%" echo id_nodo=%ID_NODO%)
>> "%CONFIG%" echo.
>> "%CONFIG%" echo [red]
>> "%CONFIG%" echo ip_servidor=%IP_SERVIDOR%
>> "%CONFIG%" echo puerto_udp=%PUERTO_UDP%
>> "%CONFIG%" echo puerto_cmd=%PUERTO_CMD%
>> "%CONFIG%" echo intervalo=3
exit /b 0
