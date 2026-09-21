@echo off
setlocal
cd /d "%~dp0"
py -3 -m pip install -r requirements.txt
py -3 -m salem_tv_box_emulator
