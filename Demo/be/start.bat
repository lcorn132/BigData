@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Chua cai dat. Hay chay setup.bat voi duong dan ZIP serving_export.
  exit /b 1
)
if exist "hdfs.env.bat" (
  call hdfs.env.bat
)

if /I "%HDFS_SYNC_ENABLED%"=="true" (
  .venv\Scripts\python.exe prepare_data.py
  if errorlevel 1 (
    if not exist "data\cosmetics.db" exit /b 1
    echo Khong ket noi duoc HDFS. Tiep tuc bang SQLite cache gan nhat.
  )
)

if not exist "data\cosmetics.db" (
  echo Chua co du lieu. Hay cau hinh hdfs.env.bat hoac chay setup.bat voi ZIP.
  exit /b 1
)

.venv\Scripts\python.exe catalog_enrichment.py --database data\cosmetics.db
if errorlevel 1 exit /b 1

set DATA_BACKEND=sqlite
set DATABASE_PATH=%CD%\data\cosmetics.db
set FRONTEND_DIR=%CD%\..\fe
set USE_REDIS=false
set CORS_ORIGINS=http://localhost:8000,http://127.0.0.1:8000

start "" http://127.0.0.1:8000
.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
