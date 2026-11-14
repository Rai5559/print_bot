@echo off
title Cerebro de Impresion - Servidor IA
echo ===================================================
echo Iniciando el Cerebro de IA para Impresiones...
echo Asegurate de que Ollama este ejecutandose en tu PC.
echo ===================================================

:: 1. Activar el entorno virtual
echo Activando entorno virtual (venv)...
call venv\Scripts\activate

:: 2. Ejecutar el script principal
echo Iniciando bot de Telegram...
python main.py

:: 3. Si el programa se cierra por un error, pausa la pantalla para que puedas leerlo
echo.
echo ⚠️ El Cerebro se ha detenido.
pause