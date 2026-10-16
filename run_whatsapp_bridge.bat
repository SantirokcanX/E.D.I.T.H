@echo off
REM Bridge de WhatsApp para EDITH (Fase 9).
REM Normalmente EDITH lo arranca sola si WHATSAPP_ENABLED=true; usa este archivo para
REM vincular por primera vez viendo el QR en la terminal o para ver sus mensajes.
cd /d "%~dp0bridges\whatsapp"
if not exist node_modules (
    echo Instalando dependencias del bridge...
    call npm install
)
node bridge.mjs
pause
