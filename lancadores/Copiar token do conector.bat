@echo off
rem Copia para a area de transferencia o valor do cabecalho do conector.
chcp 65001 >nul
cd /d "%~dp0app" || (echo Pasta app nao encontrada. & pause & exit /b 1)
set "PYTHONPATH=%CD%\src"
set PYTHONUTF8=1
bin\uv.exe run --quiet --no-project --python 3.12 --with-requirements requisitos.txt python -m mcp_arrendamento iniciar token
pause
