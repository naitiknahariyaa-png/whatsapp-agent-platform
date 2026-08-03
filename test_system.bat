@echo off
echo ============================================
echo  WhatsApp AI Agent - Full System Test
echo ============================================
echo.

set API=http://localhost:8000
set PHONE=919876543210

rem ---- CI step: verify git submodule SHAs ----
echo [CI] Checking git submodule status...
if exist ".gitmodules" (
    git submodule status > submodule_status.txt 2>&1
    type submodule_status.txt
    rem Check for leading - or + (means SHA mismatch)
    findstr /R "^-" submodule_status.txt >nul && (
        echo [FAIL] Submodule SHA mismatch - run git submodule update
        exit /b 1
    )
    findstr /R "^+" submodule_status.txt >nul && (
        echo [FAIL] Submodule SHA mismatch - run git submodule update
        exit /b 1
    )
    echo [PASS] All submodules at locked SHA
) else (
    echo [SKIP] No .gitmodules found
)
echo.

echo [1/8] Root endpoint...
curl -s %API%/ > test_output.txt
echo Result: 
type test_output.txt
echo.

echo [2/8] Health check...
curl -s %API%/health >> test_output.txt
echo.
echo.

echo [3/8] Test: Greeting intent...
curl -s -X POST %API%/api/message -H "Content-Type: application/json" -d "{\"phone_number\": \"%PHONE%\", \"message\": \"Namaste\"}" >> test_output.txt
echo.
echo.

echo [4/8] Test: Appointment booking...
curl -s -X POST %API%/api/message -H "Content-Type: application/json" -d "{\"phone_number\": \"%PHONE%\", \"message\": \"mujhe kal 3 baje appointment chahiye\"}" >> test_output.txt
echo.
echo.

echo [5/8] Test: Pricing query...
curl -s -X POST %API%/api/message -H "Content-Type: application/json" -d "{\"phone_number\": \"%PHONE%\", \"message\": \"aapki fees kitni hai\"}" >> test_output.txt
echo.
echo.

echo [6/8] Test: Support issue...
curl -s -X POST %API%/api/message -H "Content-Type: application/json" -d "{\"phone_number\": \"%PHONE%\", \"message\": \"mujhe help chahiye\"}" >> test_output.txt
echo.
echo.

echo [7/8] Test: Farewell...
curl -s -X POST %API%/api/message -H "Content-Type: application/json" -d "{\"phone_number\": \"%PHONE%\", \"message\": \"dhanyavad\"}" >> test_output.txt
echo.
echo.

echo [8/8] Switch verticals...
curl -s -X POST "%API%/api/vertical?vertical=doctor" >> test_output.txt
curl -s -X POST "%API%/api/message" -H "Content-Type: application/json" -d "{\"phone_number\": \"%PHONE%\", \"message\": \"mujhe bukhar hai\"}" >> test_output.txt
echo.
echo.

echo ============================================
echo  All tests completed!
echo  Check test_output.txt for full results
echo ============================================
pause