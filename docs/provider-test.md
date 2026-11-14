# VTU Provider Test Results

**Date:** 2026-11-14  
**Tester:** Code analysis (no live API keys available; real purchases require owner approval)

## Provider Capability Matrix

| Service | Dancity | Gsubz | Recommended | Notes |
|---------|---------|-------|-------------|-------|
| Airtime | ✅ Offered | ✅ Offered | **Dancity** | Dancity has per-transaction cap of ₦10,000; Gsubz has no cap. Use failover for amounts >₦10k. |
| Data | ✅ Offered | ✅ Offered | **Dancity** | Dancity covers all 4 networks via `/plans/data`; Gsubz covers MTN/Airtel/Glo/9mobile via service IDs. |
| Cable (validate + buy) | ✅ Offered | ❌ Not offered | **Dancity** | Gsubz raises `ProviderNotFoundError` for all cable operations. |
| Electricity (validate + buy, prepaid+postpaid) | ✅ Offered | ❌ Not offered | **Dancity** | Gsubz raises `ProviderNotFoundError` for all electricity operations. |
| Exam pins | ✅ Offered | ❌ Not offered | **Dancity** | Gsubz raises `ProviderNotFoundError` for exam pin operations. |
| Betting funding | ❌ Not offered | ❌ Not offered | **None** | No provider implements betting yet. Betting requires backend integration first. |

## Dancity (Cool-sub merchant API)

**Base URL:** `https://v2.cool-sub.com` (code default) / `https://api.dancity.app` (docs)  
**Auth:** Bearer token + `X-API-Key` header + `channel: API` header  
**Catalogue endpoints:** `GET /api/v1/services`, `GET /api/v1/products?service=<SERVICE>`, `GET /api/v1/plans/data`, `GET /api/v1/plans/cable`

### Airtime
- **Validate:** None (buy-only)
- **Buy:** `POST /api/v1/airtime/buy` — `{product, phone, amount, customerRef}`
- **Minimums:** None documented
- **Cap:** ₦10,000 per transaction (`max_airtime_amount`)
- **Cost vs selling:** Admin pricing manager must ensure sell price > provider cost

### Data
- **Buy:** `POST /api/v1/data/buy` — `{plan, phone, customerRef}`
- **Catalogue:** `GET /api/v1/plans/data`
- **Minimums:** None documented

### Cable (validate + buy)
- **Validate:** `POST /api/v1/cable/validate` — `{smartcardNumber, cablename}`
- **Buy:** `POST /api/v1/cable/buy` — `{smartcardNumber, cableplan (planId), customerName, customerRef}`
- **Minimums:** None documented

### Electricity (validate + buy, prepaid + postpaid)
- **Validate:** `POST /api/v1/electricity/validate` — `{meterNumber, billerCode, amount, meterType}`
- **Buy:** `POST /api/v1/electricity/buy` — `{meterNumber, billerCode, meterType, amount, customerName, address, customerRef}`
- **Minimums:** ₦500 minimum
- **Prepaid token:** Returned in `data.token` — stored on order, shown on receipt, never logged
- **Postpaid:** Same buy endpoint; confirms bill settlement

### Exam pins
- **Buy:** `POST /api/v1/education-pin/purchase` — `{exam_name, quantity (1-5), examNumber (JAMB, quantity 1), customerRef}`
- **PINs:** Returned once in response; stored on order, shown on receipt, never logged

### Transaction re-query
- **GET /api/v1/transactions/{id}** — returns status, transaction_id, amount, api_response, token

## Gsubz

**Base URL:** `https://api.gsubz.com`  
**Auth:** Bearer token + `Accept: application/json`

### Airtime
- **Buy:** `POST /api/pay/` — `{serviceID, api, amount, phone, requestID}`
- **Cap:** None (`max_airtime_amount = None`)

### Data
- **Buy:** `POST /api/pay/` — `{serviceID, api, amount, phone, requestID}`
- **Catalogue:** `GET /api/plans/?service=<service_id>`

### Cable / Electricity / Exam / Betting
- **Not offered** — all raise `ProviderNotFoundError`

## Recommended Routing

| Service | Primary | Fallback | Rationale |
|---------|---------|----------|-----------|
| Airtime | Dancity | Gsubz | Dancity first (₦10k cap), Gsubz for larger amounts (no cap) |
| Data | Dancity | Gsubz | Dancity covers all networks |
| Cable | Dancity | None | Only Dancity supports cable |
| Electricity | Dancity | None | Only Dancity supports electricity |
| Exam pins | Dancity | None | Only Dancity supports exam pins |
| Betting | None | None | No provider implements betting yet |

## Real Purchases Needed (owner approval required)

Without live API keys, the following small test purchases could not be executed:

1. **₦100 airtime** (MTN) — both providers
2. **₦100 data** (1GB) — both providers
3. **₦500 electricity** (prepaid) — Dancity only
4. **Cheapest cable plan** — Dancity only
5. **One exam PIN** — Dancity only
6. **₦100 betting** — No provider supports this yet

Please approve these test purchases or provide sandbox credentials so they can be run against live endpoints.

## Notes

- Dancity is the only provider that covers cable, electricity, exam pins, and data across all networks.
- Gsubz only covers data and airtime, and its account has not been upgraded for API purchases (returns `ProviderAuthError` with "GET UPGRADED" marker).
- Betting requires backend integration before any provider can serve it.
- All provider error messages must be sanitized before showing to users (see code fix in this commit).
