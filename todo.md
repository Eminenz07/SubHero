# SubHero Admin Panel & Phase 2 — TODO Tracker

## 🔴 Admin Panel (MVP — Build Now)

### Setup
- [ ] Create `admin_panel` Django app
- [ ] Configure URL prefix `/subhero-hq/`
- [ ] Create `@staff_required` and `@ip_whitelist` decorators
- [ ] Create `base_admin.html` master layout (desktop-first, SubHero design system)
- [ ] Create AdminLog, SystemLog, AlertConfig, SystemSetting models
- [ ] Run migrations

### Dashboard
- [ ] Metric cards: users, orders, revenue, profit
- [ ] Revenue vs profit line chart (Chart.js)
- [ ] Order type donut chart
- [ ] CheapDataHub wallet balance banner
- [ ] JAP wallet balance banner
- [ ] HTMX 30s/60s auto-refresh for live metrics

### User Management
- [ ] Users table with all columns and sorting
- [ ] Search by name, phone, email
- [ ] Filter by status, date joined, balance
- [ ] User detail page (profile + transaction + order history)
- [ ] Suspend / Activate user action
- [ ] Freeze wallet action
- [ ] CSV export endpoint

### VTU Pricing Manager
- [ ] Load VTUPlan table grouped by network
- [ ] Show API cost price (read only)
- [ ] Markup type selector (% or ₦)
- [ ] Live auto-calculate sell price and profit as markup is typed
- [ ] Save per row via HTMX POST
- [ ] Bulk update by network
- [ ] Active/inactive toggle per plan

### SMM Pricing Manager
- [ ] Load SMMService table grouped by platform
- [ ] Show JAP USD rate + NGN equivalent
- [ ] Markup config and live calculation
- [ ] Save per row via HTMX POST
- [ ] Active/inactive toggle per service
- [ ] Exchange rate display and manual override

### Order Management
- [ ] Unified VTU + SMM order table
- [ ] Status colour-coded badges
- [ ] All filters (type, status, network, platform, date, search)
- [ ] Order detail view
- [ ] Manual refund action
- [ ] Retry order action
- [ ] Mark as delivered action (with reason note)

### Transaction Log
- [ ] All WalletTransaction records table
- [ ] Type and status filters
- [ ] Search by reference or phone
- [ ] Total volume summary
- [ ] CSV export

### API Wallet Monitor
- [ ] CheapDataHub balance display (live fetch)
- [ ] JAP balance display (live fetch)
- [ ] Balance history graph (14 days)
- [ ] Warning + critical threshold config inputs
- [ ] Alert email config input
- [ ] Save alert config
- [ ] Test alert button
- [ ] Celery Beat task: check_api_wallet_balances (every 2 hours)

### Live Logs
- [ ] SystemLog model and log helper function
- [ ] Instrument accounts app: registration, OTP, login events
- [ ] Instrument wallet app: fund, debit, refund, P2P events
- [ ] Instrument VTU app: order placed, API call, delivery, retry, refund
- [ ] Instrument SMM app: order placed, JAP call, poll, completion, refund
- [ ] Instrument system: Celery tasks, plan sync, catalogue sync
- [ ] SSE endpoint: /subhero-hq/logs/stream/
- [ ] Live log UI with colour-coded rows
- [ ] Filter controls (level, category, search)
- [ ] Auto-scroll toggle
- [ ] Pause/Resume stream
- [ ] Log history page (paginated)

### System Settings
- [ ] Admin IP whitelist
- [ ] Alert email
- [ ] CheapDataHub thresholds
- [ ] JAP thresholds
- [ ] USD/NGN rate and override
- [ ] Max single VTU amount
- [ ] Max P2P transfer limits
- [ ] Maintenance mode toggle
- [ ] New registrations toggle

---

## 🟡 Phase 2 — Feature Backlog (After MVP Launch)

### Trigger
- [ ] MVP hits 500 active users OR ₦1M monthly GMV
- [ ] Begin Phase 2 planning sprint

### P1 — Reseller / Agent Network
- [ ] Agent application flow (user-facing)
- [ ] Admin: approve/reject agent applications
- [ ] Agent tier system (Bronze / Silver / Gold)
- [ ] Discounted pricing per tier
- [ ] Sub-agent creation (Gold only)
- [ ] Commission calculation on sub-agent purchases
- [ ] Agent analytics dashboard

### P2 — Referral Programme
- [ ] Activate dormant referral_code field on User model
- [ ] Referral link generation (subhero.ng/r/CODE)
- [ ] Track referral on registration
- [ ] Reward logic: referrer ₦100, referee ₦50
- [ ] Monthly cap (50 referrals per user)
- [ ] Admin: configure reward amounts in System Settings
- [ ] Referral stats in user profile

### P3 — Additional VTU Services
- [ ] WAEC Result PIN (VTUPass)
- [ ] JAMB PIN (VTUPass)
- [ ] NECO PIN (VTUPass)
- [ ] Bulk SMS (Termii)
- [ ] Gift Cards (Reloadly API)
- [ ] International Airtime (Reloadly API)

### P4 — CAC & Gateway Upgrade
- [ ] Initiate CAC business name registration
- [ ] Apply for Paystack live account after CAC
- [ ] Integrate Monnify as 3rd funding option
- [ ] Upgrade Squad to business tier for higher limits

### P5 — Advanced Security
- [ ] 2FA via TOTP (django-otp) — optional users, mandatory admin
- [ ] Login anomaly detection (new IP/device alert)
- [ ] Fraud velocity scoring in Redis
- [ ] Device fingerprinting on first login

### P6 — OgaViral Integration
- [ ] Evaluate OgaViral track record after 12+ months live
- [ ] Add SMMProvider model to support multiple providers
- [ ] Admin panel toggle: which provider per service category
- [ ] Fallback: JAP fails → retry via OgaViral

### P7 — Android App
- [ ] Django REST Framework: add API layer for all mobile features
- [ ] Flutter project setup (Android-first)
- [ ] FCM push notifications (replace SMS for app users)
- [ ] All VTU, SMM, wallet, P2P features via REST API
- [ ] App Store listing (Google Play)

### P8 — Analytics Upgrades
- [ ] User cohort retention charts
- [ ] Most purchased plans ranking
- [ ] Revenue by service type breakdown
- [ ] Profit margin trend over time
- [ ] Geographic order breakdown
- [ ] PDF report export

---

## ✅ Completed (MVP Core — Phase 1)
- [x] Django project structure
- [x] PostgreSQL + Redis + Celery setup
- [x] Accounts app (register, login, OTP, PIN)
- [x] Wallet model + virtual account
- [x] Squad payment integration + webhook
- [x] VTU module (CheapDataHub)
- [x] SMM module (JustAnotherPanel)
- [x] P2P transfer
- [x] Termii SMS notifications
- [x] Frontend (Tailwind + Vanilla JS + HTMX)
- [x] Fly.io deployment

---

_Last updated: May 2026 — SubHero by SubVerse_
