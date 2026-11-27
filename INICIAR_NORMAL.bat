@echo off
chcp 65001 >nul
title SDMR - Lanzador normal
setlocal EnableExtensions

rem ============================================================================
rem  SDMR - Iniciar en modo NORMAL (sin TLS/HMAC) con doble clic.
rem  Sirve para comparar contra el modo seguro (ver el antes/despues en Wireshark)
rem  y para una demo rapida sin certificados. El login PBKDF2 y los roles (RBAC)
rem  funcionan igual. Para apagar: doble clic en DETENER_SEGURO.bat
rem ============================================================================

cd /d "%~dp0"

echo ================================================================
echo   SDMR - INICIAR EN MODO NORMAL (sin cifrado)
echo ================================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] No se encontro "python" en el PATH.
  pause
  exit /b 1
)

rem Web compilada (solo la primera vez)
if not exist "web\dist\index.html" (
  echo [SETUP] Compilando la web por primera vez con npm (puede tardar)...
  pushd web
  call npm install
  call npm run build
  popd
  echo.
)

echo Levantando el stack NORMAL...
echo.

start "SDMR - Servidor (normal)"  cmd /k python server\server.py
timeout /t 3 /nobreak >nul
start "SDMR - Agente NODO_01"     cmd /k python agent\agent.py NODO_01 127.0.0.1 5000 5002
start "SDMR - Agente NODO_02"     cmd /k python agent\agent.py NODO_02 127.0.0.1 5000 5004
start "SDMR - Gateway + Web"      cmd /k python server\gateway.py 5003 127.0.0.1 5001 --serve-web
timeout /t 5 /nobreak >nul

start "" http://localhost:5173

echo.
echo ================================================================
echo   LISTO. Se abrio la web: http://localhost:5173
echo   Usuarios:  admin / admin123    operador / operador123
echo   Para apagar todo: doble clic en  DETENER_SEGURO.bat
echo ================================================================
echo.
pause
