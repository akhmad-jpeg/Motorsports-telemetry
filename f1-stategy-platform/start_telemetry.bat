@echo off
cls
echo ============================================================
echo F1 2018 TELEMETRY CAPTURE - SESSION SETUP
echo ============================================================
echo.

REM Get track name
set /p TRACK="Enter Track Name (e.g., Spa, Monaco, Silverstone): "

REM Get tyre compound
echo.
echo Tyre Compounds: Hypersoft, Ultrasoft, Supersoft, Soft, Medium, Hard, Intermediate, Wet
set /p TYRE="Enter Starting Tyre Compound: "

REM Get weather
echo.
set /p WEATHER="Enter Weather (Clear, Rain, Cloudy): "

echo.
echo ============================================================
echo SESSION CONFIGURATION
echo ============================================================
echo Track:   %TRACK%
echo Tyres:   %TYRE%
echo Weather: %WEATHER%
echo ============================================================
echo.

REM Update the Python script
powershell -Command "(gc scripts\capture_telemetry.py) -replace 'TRACK_NAME = \".*\"', 'TRACK_NAME = \"%TRACK%\"' | Out-File -encoding ASCII scripts\capture_telemetry.py"
powershell -Command "(gc scripts\capture_telemetry.py) -replace 'STARTING_TYRE = \".*\"', 'STARTING_TYRE = \"%TYRE%\"' | Out-File -encoding ASCII scripts\capture_telemetry.py"
powershell -Command "(gc scripts\capture_telemetry.py) -replace 'WEATHER = \".*\"', 'WEATHER = \"%WEATHER%\"' | Out-File -encoding ASCII scripts\capture_telemetry.py"

echo Configuration updated!
echo.
echo Starting telemetry capture...
echo Press Ctrl+C to stop capturing.
echo.

REM Run the Python script
python scripts\capture_telemetry.py

pause
