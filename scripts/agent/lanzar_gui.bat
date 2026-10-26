@echo off
setlocal
cd /d "%~dp0..\.."
set "RAIZ=%CD%"
where py >nul 2>nul
if %errorlevel%==0 ( set "PY=py -3" ) else ( set "PY=python" )
start "" %PY% "%RAIZ%\scripts\agent\agent_control.py"
endlocal
exit /b 0
