@echo off
REM ============================================================================
REM  SDMR - Detener la demo automatica (Windows)
REM  Mata los procesos python/pythonw que esten corriendo server.py o agent.py.
REM ============================================================================
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$targets = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*server.py*' -or $_.CommandLine -like '*agent.py*' }; if ($targets) { $targets | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; Write-Output ('Detenidos ' + $targets.Count + ' proceso(s).') } else { Write-Output 'No hay procesos SDMR corriendo.' }"
endlocal
exit /b 0
