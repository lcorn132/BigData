@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Khong tim thay Python Launcher. Hay cai Python 3.10 tro len.
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if not "%~1"=="" (
  python import_data.py --backend sqlite --input "%~1" --database data\cosmetics.db --reset
  if errorlevel 1 exit /b 1
)

echo.
echo Da cai dat. Neu chua nap ZIP truc tiep, hay cau hinh hdfs.env.bat.
echo Chay start.bat de dong bo HDFS va mo ung dung.
