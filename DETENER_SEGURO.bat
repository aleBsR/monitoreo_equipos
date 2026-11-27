@echo off
chcp 65001 >nul
title Detener SDMR
setlocal EnableExtensions

rem ============================================================================
rem  Cierra todas las ventanas del SDMR abiertas por INICIAR_SEGURO.bat.
rem  (Tambien podes cerrar cada ventana a mano: cada una es un componente.)
rem ============================================================================

echo Cerrando los componentes del SDMR...

rem Las ventanas lanzadas tienen titulos que empiezan con "SDMR -".
taskkill /F /T /FI "WINDOWTITLE eq SDMR -*" >nul 2>nul

echo.
echo Listo. Todos los componentes del SDMR fueron cerrados.
echo (Si quedo alguna ventana abierta, cerrala a mano.)
timeout /t 3 /nobreak >nul
