@setlocal enabledelayedexpansion
call ./venv/Scripts/activate.bat

for /F "tokens=*" %%a in ('type .env') do (
  set "%%a!"
)

echo !HOST_URL! !PORT!

call python app.py