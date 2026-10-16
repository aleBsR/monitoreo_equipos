@echo off
REM ============================================================================
REM  SDMR - Todo en uno para Windows (doble clic)
REM  Levanta: Servidor TCP/UDP + Gateway WS + 2 Agentes + Web compilada
REM  Luego abri: http://127.0.0.1:5173  y  Expo Go -> ws://TU_IP:5003
REM ============================================================================
setlocal
cd /d "%~dp0.."

where py >nul 2>nul
if %errorlevel%==0 ( set "PY=py -3" ) else ( set "PY=python" )

%PY% --version >nul 2>nul
if errorlevel 1 (
  echo ERROR: No se encontro Python 3. Instalalo y tilda "Add Python to PATH".
  pause
  exit /b 1
)

%PY% -c "import websockets" >nul 2>nul
if errorlevel 1 (
  echo Instalando 'websockets' para el gateway...
  %PY% -m pip install websockets
)

if not exist "web\dist\index.html" (
  echo Compilando web React...
  pushd web
  where npm >nul 2>nul
  if errorlevel 1 (
    echo ERROR: Falta Node.js para compilar la web. Instalalo de nodejs.org
    popd
    pause
    exit /b 1
  )
  call npm install --no-audit --no-fund
  call npm run build
  popd
)

echo Cerrando procesos SDMR anteriores...
taskkill /F /IM python.exe /FI "WINDOWTITLE eq SDMR*" >nul 2>nul

echo [1/4] Servidor central UDP 5000 + TCP 5001...
start "SDMR Servidor" %PY% -u server\server.py 5000 5001
timeout /t 2 /nobreak >nul

echo [2/4] Gateway WS 5003 + web http://127.0.0.1:5173...
start "SDMR Gateway" %PY% -u server\gateway.py 5003 127.0.0.1 5001 --serve-web
timeout /t 2 /nobreak >nul

echo [3/4] Agentes NODO_01 y NODO_02...
start "SDMR NODO_01" %PY% -u agent\agent.py NODO_01 127.0.0.1 5000 5002
start "SDMR NODO_02" %PY% -u agent\agent.py NODO_02 127.0.0.1 5000 5004
timeout /t 2 /nobreak >nul

echo [4/4] Verificando red local...
%PY% -u tools\verificar_red.py 127.0.0.1 5000 5001 5003

echo.
echo ============================================================================
echo  TODO LISTO. Probalo asi:
echo   Web local:   http://127.0.0.1:5173  login ws://127.0.0.1:5003 admin/admin123
echo   CLI:         python client\admin_client.py 127.0.0.1 5001
echo   Tkinter:     python client\gui_monitor.py --demo
echo   Red/hotspot: ipconfig -^> IPv4 (ej. 192.168.43.10)
echo                web: http://192.168.43.10:5173
echo                movil Expo Go: ws://192.168.43.10:5003
echo ============================================================================
echo  Para cerrar todo: cierra las ventanas "SDMR *".
echo.
start http://127.0.0.1:5173
pause
endlocal
