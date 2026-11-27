@echo off
chcp 65001 >nul
title SDMR - Lanzador seguro
setlocal EnableExtensions

rem ============================================================================
rem  SDMR - Iniciar en modo SEGURO (TLS + HMAC + PBKDF2 + RBAC) con doble clic
rem ----------------------------------------------------------------------------
rem  La PRIMERA vez hace el setup solo (certificados, usuarios, clave, web).
rem  Despues levanta servidor + 2 agentes + gateway en modo seguro y abre la web.
rem  Todo corre en esta PC (localhost). Para apagar: doble clic en DETENER_SEGURO.bat
rem ============================================================================

rem Ir a la carpeta del proyecto (donde esta este .bat)
cd /d "%~dp0"

echo ================================================================
echo   SDMR - INICIAR EN MODO SEGURO
echo   TLS 1.3 + HMAC (UDP) + contrasenas PBKDF2 + roles (RBAC)
echo ================================================================
echo.

rem --- 1. Verificar Python -----------------------------------------------------
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] No se encontro "python" en el PATH.
  echo         Instala Python 3 y volve a intentar.
  echo.
  pause
  exit /b 1
)

rem --- 2. Certificados TLS (solo la primera vez) -------------------------------
if not exist "certs\server.pem" (
  echo [SETUP] Generando certificados TLS por primera vez...
  python -m pip install cryptography --quiet
  python scripts\gen_certs.py
  echo.
)

rem --- 3. Usuarios con contrasena hasheada PBKDF2 (solo la primera vez) --------
if not exist "server\usuarios.json" (
  echo [SETUP] Creando usuarios admin / operador (PBKDF2)...
  python scripts\set_password.py admin --rol admin --password admin123
  python scripts\set_password.py operador --rol operador --password operador123
  echo.
)

rem --- 4. Clave HMAC compartida (se crea una vez y se reutiliza) ---------------
if not exist "certs\hmac.key" (
  echo [SETUP] Generando clave HMAC compartida...
  python -c "from common import security; print(security.generar_clave_hmac_hex())" > "certs\hmac.key"
)
set /p SDMR_HMAC_KEY=<certs\hmac.key

rem --- 5. Web compilada (solo la primera vez; usa npm) ------------------------
if not exist "web\dist\index.html" (
  echo [SETUP] Compilando la web por primera vez con npm (puede tardar)...
  pushd web
  call npm install
  call npm run build
  popd
  echo.
)

echo [OK] Todo listo. Levantando el stack SEGURO...
echo.

rem --- 6. Levantar cada componente en su propia ventana -----------------------
start "SDMR - Servidor (seguro)"  cmd /k python server\server.py --seguro
timeout /t 3 /nobreak >nul
start "SDMR - Agente NODO_01"     cmd /k python agent\agent.py NODO_01 127.0.0.1 5000 5002 --seguro
start "SDMR - Agente NODO_02"     cmd /k python agent\agent.py NODO_02 127.0.0.1 5000 5004 --seguro
start "SDMR - Gateway + Web"      cmd /k python server\gateway.py 5003 127.0.0.1 5001 --seguro --serve-web
timeout /t 5 /nobreak >nul

rem --- 7. Abrir la web en el navegador ---------------------------------------
start "" http://localhost:5173

echo.
echo ================================================================
echo   LISTO. Se abrio la web: http://localhost:5173
echo.
echo   Usuarios de prueba:
echo       admin    / admin123      (puede ejecutar EXEC)
echo       operador / operador123   (solo lectura, NO ejecuta)
echo.
echo   Para apagar todo: doble clic en  DETENER_SEGURO.bat
echo ================================================================
echo.
echo (Podes cerrar esta ventana; las demas quedan corriendo.)
pause
