@echo off
setlocal
title Deploy COC Control - VPS Hostinger
REM ==================== CONFIG (edite se precisar) ====================
set "VPS_USER=root"
set "VPS_HOST=2.25.137.114"
set "COC_DOMAIN=coccontrol.chriscsantosqa.tech"
REM ====================================================================
cd /d "%~dp0"

where ssh >nul 2>nul || (echo [erro] Cliente OpenSSH nao encontrado. Instale: Configuracoes ^> Aplicativos ^> Recursos opcionais ^> Cliente OpenSSH. & pause & exit /b 1)
where tar >nul 2>nul || (echo [erro] tar nao encontrado ^(Windows 10+ ja inclui^). & pause & exit /b 1)

echo ==============================================================
echo  Deploy do COC Control em %VPS_USER%@%VPS_HOST%
echo  Dominio: https://%COC_DOMAIN%
echo.
echo  Voce digitara a senha da VPS 2 vezes (upload + instalacao).
echo  Na primeira execucao o instalador pergunta usuario e senha
echo  de LOGIN do COC Control (nao confundir com a senha da VPS).
echo ==============================================================
echo.

echo [1/3] Empacotando projeto...
if exist coc-control-deploy.tar.gz del coc-control-deploy.tar.gz
tar -czf coc-control-deploy.tar.gz --exclude=__pycache__ --exclude=*.pyc --exclude=.env --exclude=*.db --exclude=*.db-journal --exclude=coc-control-deploy.tar.gz -C .. coc-control
if errorlevel 1 (echo [erro] falha ao empacotar & pause & exit /b 1)

echo [2/3] Enviando para a VPS (senha 1/2)...
scp coc-control-deploy.tar.gz %VPS_USER%@%VPS_HOST%:/tmp/
if errorlevel 1 (echo [erro] falha no upload & pause & exit /b 1)

echo [3/3] Instalando na VPS (senha 2/2)...
ssh -t %VPS_USER%@%VPS_HOST% "tar -xzf /tmp/coc-control-deploy.tar.gz -C /opt/ && sed -i 's/\r$//' /opt/coc-control/deploy/*.sh && COC_DOMAIN=%COC_DOMAIN% bash /opt/coc-control/deploy/install_vps.sh && rm -f /tmp/coc-control-deploy.tar.gz"
if errorlevel 1 (echo. & echo [erro] instalacao retornou erro - veja as mensagens acima. & pause & exit /b 1)

del coc-control-deploy.tar.gz >nul 2>nul
echo.
echo ==============================================================
echo  Pronto! Acesse: https://%COC_DOMAIN%
echo  Se o DNS ainda nao existe, crie o registro A:
echo    coccontrol  -^>  %VPS_HOST%
echo  (o certificado HTTPS e emitido sozinho quando o DNS apontar)
echo ==============================================================
pause
