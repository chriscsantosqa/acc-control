@echo off
title COC Control
cd /d "%~dp0"
where python >nul 2>nul || (echo Python nao encontrado. Instale em https://python.org (marque "Add to PATH") & pause & exit /b)
pip show flask >nul 2>nul || (echo Instalando dependencias... & pip install -r requirements.txt)
python app.py
pause
