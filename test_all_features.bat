@echo off
echo ============================================
echo WhatsApp AI Agent Platform - Full Test Suite
echo ============================================
echo.

echo [TEST 1] Health Check
curl -s http://localhost:8000/health
echo.
echo.

echo [TEST 2] Stats Endpoint
curl -s http://localhost:8000/stats
echo.
echo.

echo [TEST 3] Webhook - Greeting Message
curl -s -X POST http://localhost:8000/webhook -H "Content-Type: application/json" -d "{\"from\": \"9111111111\", \"body\": \"Namaste\"}"
echo.
echo.

echo [TEST 4] Webhook - Appointment Booking
curl -s -X POST http://localhost:8000/webhook -H "Content-Type: application/json" -d "{\"from\": \"9111111111\", \"body\": \"Mujhe appointment chahiye kal 7 baje\"}"
echo.
echo.

echo [TEST 5] Webhook - Order Placement
curl -s -X POST http://localhost:8000/webhook -H "Content-Type: application/json" -d "{\"from\": \"9111111111\", \"body\": \"Mujhe 2 pizzas chahiye\"}"
echo.
echo.

echo [TEST 6] Webhook - Human Handoff
curl -s -X POST http://localhost:8000/webhook -H "Content-Type: application/json" -d "{\"from\": \"9111111111\", \"body\": \"I want to talk to human\"}"
echo.
echo.

echo [TEST 7] API Message Endpoint
curl -s -X POST http://localhost:8000/api/message -H "Content-Type: application/json" -d "{\"phone_number\": \"9111111111\", \"message\": \"Hello\"}"
echo.
echo.

echo ============================================
echo All tests completed!
echo ============================================
pause