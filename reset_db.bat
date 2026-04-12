@echo off
echo ===========================================
echo  AMPARO - Reset base de datos
echo ===========================================
echo.

cd /d "d:\Proyecto Amparo\Amparo"

echo Cerrando procesos Python existentes...
taskkill /F /IM python.exe >nul 2>&1
taskkill /F /IM pythonw.exe >nul 2>&1
ping -n 3 127.0.0.1 >nul

echo Eliminando base de datos antigua...
if exist amparo.db (
    del /F amparo.db
    if exist amparo.db echo ERROR: No se pudo borrar amparo.db
    if not exist amparo.db echo OK: amparo.db eliminado
)
if exist amparo.db-journal del /F amparo.db-journal
if exist amparo.db-wal del /F amparo.db-wal
if exist amparo.db-shm del /F amparo.db-shm

echo Recreando base de datos...
.venv\Scripts\python.exe init_db.py
if errorlevel 1 (
    echo ERROR al crear la base de datos
    pause
    exit /b 1
)

echo Restaurando redacciones de correos...
.venv\Scripts\python.exe restaurar_correos.py

echo.
echo ===========================================
echo  Listo. Ejecuta app.py para iniciar Flask.
echo ===========================================
pause
