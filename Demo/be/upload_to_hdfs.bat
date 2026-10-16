@echo off
setlocal
cd /d "%~dp0"

if not exist "hdfs.env.bat" (
  echo Hay sao chep hdfs.env.example.bat thanh hdfs.env.bat va dien cau hinh.
  exit /b 1
)
if "%~1"=="" (
  echo Cach dung: upload_to_hdfs.bat "C:\duong-dan\serving_export_....zip"
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Hay chay setup.bat truoc.
  exit /b 1
)

call hdfs.env.bat
.venv\Scripts\python.exe hdfs_sync.py upload --input "%~1"
if errorlevel 1 exit /b 1
echo Da dua serving_export len HDFS: %HDFS_EXPORT_PATH%
