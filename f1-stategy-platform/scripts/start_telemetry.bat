@echo off
cls
echo ============================================================
echo F1 2017/2018 TELEMETRY CAPTURE - SESSION SETUP
echo ============================================================
echo.

REM Get track name
echo Tracks (must match a name in the tracks table or a known alias):
echo   Examples: Sochi, Monaco, Spa, Silverstone, Bahrain, Monza, Suzuka
set /p TRACK="Enter Track Name: "

REM Get tyre compound
echo.
echo Tyre Compounds (choose one):
echo   Hypersoft  Ultrasoft  Supersoft  Soft  Medium  Hard
echo   Intermediate  Wet
set /p TYRE="Enter Starting Tyre Compound: "

REM Get weather
echo.
echo Weather options: Dry  Wet  Mixed
echo   (Also accepted: Clear, Rain, Cloudy, Showers, Overcast)
set /p WEATHER="Enter Weather: "

echo.
echo ============================================================
echo SESSION CONFIGURATION
echo ============================================================
echo   Track   : %TRACK%
echo   Tyre    : %TYRE%
echo   Weather : %WEATHER%
echo   Driver  : 0 (Player - game telemetry sentinel)
echo ============================================================
echo.
echo Starting telemetry capture...
echo Press Ctrl+C to stop.
python "%~dp0capture_telemetry.py" --track "%TRACK%" --tyre "%TYRE%" --weather "%WEATHER%"

pause