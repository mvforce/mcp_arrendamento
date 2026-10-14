#!/bin/bash
# Copia para a área de transferência o valor do cabeçalho do conector.
cd "$(dirname "$0")/app" || { echo "Pasta 'app' não encontrada ao lado deste arquivo."; read -r; exit 1; }
case "$(uname -m)" in arm64) UV="bin/uv-arm64" ;; *) UV="bin/uv-x86_64" ;; esac
xattr -d com.apple.quarantine "$UV" 2>/dev/null
export PYTHONPATH="$PWD/src"
"$UV" run --quiet --no-project --python 3.12 --with-requirements requisitos.txt python -m mcp_arrendamento iniciar token
