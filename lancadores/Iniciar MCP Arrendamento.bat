@echo off
rem Liga o MCP Arrendamento neste computador. Clique duas vezes; deixe a janela aberta.
chcp 65001 >nul
title MCP Arrendamento
cd /d "%~dp0app" || (echo Pasta app nao encontrada ao lado deste arquivo. & pause & exit /b 1)
set "PYTHONPATH=%CD%\src"
set PYTHONUTF8=1
echo   Preparando (na primeira vez baixa o Python e as bibliotecas; pode levar alguns minutos)...
bin\uv.exe run --quiet --no-project --python 3.12 --with-requirements requisitos.txt python -m mcp_arrendamento iniciar %*
echo.
pause
