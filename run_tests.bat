@echo off
cd /d "%~dp0"
echo ===================================================
echo   GalaxyCamPro - Suite de Pruebas Unitarias Backend
echo ===================================================
echo.
py test_engine.py
echo.
echo --- Modulos (tests/) ---
py -m unittest discover -s tests -t .
echo.
pause
