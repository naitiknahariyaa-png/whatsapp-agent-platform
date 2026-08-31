# WhatsApp Agent Platform — Working-Condition Checklist

Use this to verify each service individually and in combination before wiring the next one.
Do not proceed to the next service until the current one passes all checks.

---

## Service 1: Backend API

**Owner:** Backend Team  
**Dependencies:** None  
**Port:** 8000

### Checks
- [ ] `python -m uvicorn main:app --app-dir agent-engine --host 0.0.0.0 --port 8000` starts without errors
- [ ] `GET /health` returns `{"status":"ok"}`
- [ ] `POST /auth/login` with `owner@whatsappagent.com` / `owner123` returns 200 + JWT
- [ ] `GET /api/dashboard/stats` returns 200 with stats object
- [ ] `GET /api/catalog` returns 200 with array
- [ ] `GET /api/leads` returns 200 with array

**Status:** ✅ PASS (verified 2026-08-21)

---

## Service 2: Owner App (Web)

**Owner:** Frontend Team  
**Dependencies:** Backend API (Service 1)  
**URL:** `http://localhost:8000/owner-app/`

### Checks
- [ ] `launch-owner-app.bat` opens app in browser
- [ ] Login screen shows default credentials hint
- [ ] Login with `owner@whatsappagent.com` / `owner123` succeeds
- [ ] Home tab shows KPI cards (Messages, Leads, Revenue, Appointments)
- [ ] Analytics tab loads funnel chart
- [ ] Catalog tab loads items
- [ ] Leads tab loads leads list
- [ ] Bottom nav switches between tabs

**Status:** ✅ PASS (verified 2026-08-21)

---

## Service 3: Flutter Multi-Platform App

**Owner:** Mobile/Desktop Team  
**Dependencies:** Backend API (Service 1)  
**Platforms:** Android, iOS, Windows, macOS, Linux, Web

### Checks
- [ ] `flutter run -d windows` launches app on Windows
- [ ] `flutter run -d chrome` launches app in browser
- [ ] `flutter run -d android` launches app on Android device
- [ ] Login screen accepts default credentials
- [ ] Dashboard loads data from backend
- [ ] Navigation between tabs works
- [ ] WebSocket connection stays alive
- [ ] Offline mode shows cached data

**Status:** ⏳ SCAFFOLDED — needs Flutter SDK to run

---

## Service 4: WhatsApp Bridge

**Owner:** Bridge Team  
**Dependencies:** Backend API (Service 1)  
**Port:** 3001

### Checks
- [ ] `node bridge.js` starts without errors
- [ ] `GET http://localhost:3001/health` returns 200
- [ ] QR code displays for WhatsApp Web auth
- [ ] Incoming WhatsApp messages appear in backend logs
- [ ] Outgoing messages reach WhatsApp

**Status:** ⏳ SCAFFOLDED — needs Node.js + WhatsApp session

---

## Service 5: Advisory Suite (CA, Legal, MBA)

**Owner:** AI Team  
**Dependencies:** Backend API (Service 1), Manager Agent  
**Endpoints:**
- `POST /api/advisory/chat`
- `GET /api/advisory/history`

### Checks
- [ ] CA Advisor responds to tax questions
- [ ] Legal Advisor responds to compliance questions
- [ ] Business Strategist responds to growth questions
- [ ] Responses include data from backend (financials, metrics)
- [ ] Escalation works for complex queries
- [ ] Flutter Advisory screen shows all 3 advisors
- [ ] Chat UI works for all 3 advisors

**Status:** ✅ BACKEND AGENTS CREATED — routes added, needs testing

---

## Service 6: Automated Loops

**Owner:** Automation Team  
**Dependencies:** Backend API (Service 1), Database

### Checks
- [ ] Lead Nurture Loop enrolls new leads
- [ ] Appointment Guard sends reminders
- [ ] Re-engagement Loop scans cold leads
- [ ] Weekly Report generates metrics
- [ ] All loops respect opt-out keywords

**Status:** ✅ CODE READY — needs runtime verification

---

## Service 7: Android Control Center

**Owner:** Mobile Team  
**Dependencies:** Backend API (Service 1)  
**Package:** `com.whatsappagent.platform`

### Checks
- [ ] App installs on Android device
- [ ] Login works
- [ ] Dashboard shows real-time stats
- [ ] Live Chat Monitor shows conversations
- [ ] One-tap human takeover works
- [ ] Push notifications received for hot leads

**Status:** ⏳ SCAFFOLDED — needs Android Studio build

---

## Integration Test Chain

Run these in order. Do not proceed if any fails.

### Chain A: Auth + Dashboard
1. Start backend (`launch-owner-app.bat`)
2. Open `http://localhost:8000/owner-app/`
3. Login with default credentials
4. Verify dashboard loads with real data

### Chain B: Advisory Suite
1. Start backend
2. Open Owner App → Advisory tab
3. Select CA Advisor
4. Ask: "What are my tax obligations for this month?"
5. Verify response includes actual financial data

### Chain C: WhatsApp Flow
1. Start backend + bridge
2. Send WhatsApp message to test number
3. Verify Manager Agent receives and routes
4. Verify response sent back to WhatsApp

### Chain D: Flutter Desktop
1. Run Flutter app on Windows
2. Login with default credentials
3. Navigate all tabs
4. Verify data matches web app

---

## Known Issues & Mitigations

| Issue | Mitigation |
|-------|-----------|
| SQLite DB locked on restart | Delete `wap_data.db` before restart |
| Port 8000 in use | Run `stop-owner-app.bat` first |
| Flutter not installed | Install from https://flutter.dev |
| Bridge needs WhatsApp session | Scan QR on first run |
| Advisory agents need LLM | Set `GROQ_API_KEY` in `.env` |

---

## Next Steps

1. Install Flutter SDK to test the multi-platform app
2. Run Chain A integration test
3. Run Chain B integration test for Advisory Suite
4. Test WhatsApp bridge with real number
5. Build Android APK for control center
