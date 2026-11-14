@echo off
title Servidor de Impresion - Tienda
echo ===================================================
echo Iniciando Servidor Local de Impresion...
echo Mantenga esta ventana abierta para recibir trabajos
echo ===================================================

:: Esto le dice al bat que use el Python portátil de la subcarpeta
.\python_core\python.exe api_tienda.py

pause