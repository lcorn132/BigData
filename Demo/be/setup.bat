@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_CMD="
where py >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py -3"

if not defined PYTHON_CMD (
  where python >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
  echo Khong tim thay Python. Hay cai Python 3.10 tro len, sau do mo lai PowerShell.
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" %PYTHON_CMD% -m venv .venv
if errorlevel 1 exit /b 1
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
