@echo off
REM ============================================================================
REM  SDMR - Lanzador para Windows
REM ============================================================================
REM  Abre el dashboard y levanta servidor + agentes automaticamente.
REM  Hace doble clic en este archivo, o usa el acceso directo del Escritorio
REM  (crear_acceso_directo.bat).
REM ============================================================================
setlocal
cd /d "%~dp0"

REM Elegir interprete: se prefiere el lanzador 'py' (Python Launcher)
where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
) else (
    set "PY=python"
)

REM Verificar que Python exista
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

REM Verificar Tkinter (interfaz grafica)
%PY% -c "import tkinter" >nul 2>nul
if errorlevel 1 (
    echo.
    echo ERROR: Falta tkinter ^(la interfaz grafica de Python^).
    echo Reinstala Python desde python.org y asegurate de tildar la opcion
    echo "tcl/tk and IDLE" en el instalador.
    echo.
    pause
    exit /b 1
)

echo Iniciando SDMR (dashboard + servidor + agentes)...
%PY% -u client\gui_monitor.py --demo %*

if errorlevel 1 (
    echo.
    echo El dashboard finalizo con error.
    pause
)
endlocal
