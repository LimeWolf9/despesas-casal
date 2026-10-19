@echo off
REM Arranca o dashboard e mostra o endereco para o telemovel.
cd /d "%~dp0"
echo.
echo  Dashboard de despesas
echo  ---------------------
echo  Endereco(s) deste PC na rede de casa:
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do echo    http://%%a:8501
echo.
echo  Abre esse endereco no telemovel (tem de estar no mesmo Wi-Fi).
echo  Para parar: fecha esta janela ou Ctrl+C.
echo.
streamlit run app.py
