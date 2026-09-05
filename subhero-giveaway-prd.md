# SubHero Giveaway Feature — Full Product Requirements Document
## Version 1.0 | May 2026 | SubVerse Internal — Confidential

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Feature Overview & Vision](#2-feature-overview--vision)
3. [Why This Feature Exists](#3-why-this-feature-exists)
4. [User Personas](#4-user-personas)
5. [Complete Feature Logic](#5-complete-feature-logic)
6. [Data Architecture](#6-data-architecture)
7. [Security Architecture](#7-security-architecture)
8. [Growth & Acquisition Engine](#8-growth--acquisition-engine)
9. [Brand Advertising Engine](#9-brand-advertising-engine)
10. [Lead Conversion Funnels](#10-lead-conversion-funnels)
11. [Retention Mechanics](#11-retention-mechanics)
12. [Revenue Model](#12-revenue-model)
13. [Page Inventory & UX Specification](#13-page-inventory--ux-specification)
14. [API & Integration Spec](#14-api--integration-spec)
15. [Admin Panel Requirements](#15-admin-panel-requirements)
16. [Celery Tasks & Background Jobs](#16-celery-tasks--background-jobs)
17. [Metrics & Success Criteria](#17-metrics--success-criteria)
18. [Phase 2 Giveaway Extensions](#18-phase-2-giveaway-extensions)
19. [Out of Scope (MVP)](#19-out-of-scope-mvp)

---

## 1. Executive Summary

The SubHero Giveaway feature is a viral data and airtime distribution system that allows registered SubHero users to host giveaways for any number of recipients — who claim their reward via a shareable link or custom QR code, without needing to create an account.

Every giveaway is simultaneously:
- A **product** (useful for hosts who want to reward their audience)
- A **growth engine** (every claimant is exposed to SubHero and nudged to register)
- A **free advertisement** (SubHero branding is on every link, QR code, and SMS)
- A **revenue event** (SubHero earns its VTU margin on every claim delivered)

This is the highest-leverage feature SubHero can build at this stage. It turns every active user into a recruiter, every giveaway into a marketing campaign, and every free data delivery into a warm lead.

---

## 2. Feature Overview & Vision

### What It Is

A system where a SubHero user (the **Host**) can:

1. Lock funds from their SubHero wallet into a giveaway
2. Specify: reward type (data or airtime), network, amount per person, number of people
3. Receive a unique shareable link and a custom-branded QR code
4. Share the link on WhatsApp, Instagram, TikTok, Twitter — anywhere
5. Watch recipients claim their reward in real time

And where a recipient (the **Claimant**) can:

1. Open the link on any phone — no app, no account, no login
2. Enter only their phone number
3. Receive data or airtime within seconds
4. Be shown a compelling reason to create their own SubHero account

### The Vision in One Sentence

> Make every Nigerian who sends a giveaway an unpaid SubHero brand ambassador, and make every person who receives one a warm lead with a reason to join.

---

## 3. Why This Feature Exists

### The Problem It Solves for Hosts

Nigerian content creators, business owners, community leaders, and individuals regularly run giveaways. Currently they:
- Send individual bank transfers (slow, manual, error-prone)
- Use clunky Google Form → manual verification → individual transfer flows
- Pay full retail network prices for data they buy as gifts
- Have no way to track who claimed what or manage slots

SubHero solves all of this: instant, automatic, cheap, tracked.

### The Problem It Solves for SubHero

SubHero's hardest problem is customer acquisition. Paid advertising in Nigeria is expensive and conversion rates are low. The giveaway feature creates a **zero-cost distribution channel** where:

- Hosts do the marketing (they share the link to their own audiences)
- Claimants are pre-qualified leads (they've already received value from SubHero)
- Every successful delivery is proof that SubHero works
- The entire flow happens at SubHero's domain and brand

### The Network Effect

```
1 host with 1,000 Instagram followers runs a 50-slot giveaway
→ 50 people click the link
→ 50 people see SubHero branding and receive value
→ ~10–15 create accounts (20–30% conversion, warm leads)
→ 5–8 fund their wallets and make purchases
→ 3–5 run their own giveaways

That's 3–5 new giveaway hosts from 1 original host.
Each of those reaches their own audiences.
This is compounding, organic growth.
```

---

## 4. User Personas

### Persona 1 — The Content Creator
**Name:** Adaeze, 23, Lagos  
**Platform:** TikTok (18k followers), Instagram (9k)  
**Behaviour:** Runs monthly giveaways to boost engagement. Currently does bank transfers manually. Spends 2–3 hours per giveaway on logistics.  
**SubHero value:** Create a 100-slot 1GB MTN giveaway in 2 minutes. Share the link in her TikTok bio. 100 people claim automatically. She does zero manual work.  
**Acquisition value:** Her 18k followers see SubHero. High-quality audience for conversion.

### Persona 2 — The Student Union / Association Leader
**Name:** Emeka, 21, Adeleke University  
**Context:** Just won treasurer of AUSA. Wants to celebrate with members.  
**Behaviour:** Wants to send ₦200 airtime to 200 students.  
**SubHero value:** Creates a 200-slot airtime giveaway, shares the link in the AUSA WhatsApp group. Done in 5 minutes.  
**Acquisition value:** 200 university students see SubHero. Students are exactly SubHero's core demographic.

### Persona 3 — The Small Business Owner
**Name:** Rasheed, 35, Ibadan  
**Context:** Runs a fabric business. Wants to reward loyal customers.  
**Behaviour:** Monthly customer appreciation — "first 30 customers this month get free data."  
**SubHero value:** Giveaway link sent in customer WhatsApp group. Recurring monthly use case.  
**Acquisition value:** His customers are business owners and working-class Nigerians — ideal SubHero users.

### Persona 4 — The Religious/Community Leader
**Name:** Pastor Chukwu, 45, Port Harcourt  
**Context:** Church WhatsApp group of 500 members. Wants to bless members every Sunday.  
**Behaviour:** Weekly "Sunday Blessing" — 50 members get free airtime.  
**SubHero value:** Recurring weekly giveaway. High-frequency, loyal host.  
**Acquisition value:** 500 church members see SubHero every week. Strong word-of-mouth community.

### Persona 5 — The Claimant Who Becomes a Host
**Name:** Fatima, 20, Abuja  
**Context:** Claimed free 1GB data from a friend's birthday giveaway.  
**Behaviour:** Sees the success page, learns SubHero sells data cheaply. Creates account. Funds wallet. Buys data for herself. Then runs her own birthday giveaway.  
**Acquisition value:** This is the compounding loop SubHero is building for.

---

## 5. Complete Feature Logic

### 5.1 Giveaway Creation Flow (Host — Authenticated)

```
HOST OPENS /giveaway/create/
         │
         ├── Selects reward type: DATA or AIRTIME
         │
         ├── Selects network: MTN / Airtel / Glo / 9mobile
         │
         ├── If DATA: selects plan from VTUPlan table
         │     (shows: plan name, size, validity, SubHero price)
         │     e.g. "MTN 1GB — 30 Days — ₦350"
         │
         ├── If AIRTIME: enters amount per person (₦50–₦5,000)
         │
         ├── Enters number of slots (1–500)
         │
         ├── Optional: custom giveaway title
         │     default: "[Your Name]'s Giveaway 🎉"
         │
         ├── Optional: expiry date/time
         │     default: no expiry (open until all slots claimed)
         │
         ├── System AUTO-CALCULATES:
         │     Total Cost = amount_per_slot × total_slots
         │     Shows: "This giveaway will cost ₦10,000"
         │     Shows: "Your current balance: ₦15,450"
         │     Shows: "Remaining balance after: ₦5,450"
         │
         ├── Host enters Transaction PIN to confirm
         │
         └── On PIN verified:
               - ₦10,000 deducted from wallet atomically
               - Locked in GiveawayEscrow (not spent yet)
               - Unique slug generated: e.g. HERO2025ABC
               - Custom QR code generated (async)
               - Host redirected to giveaway management page
```

### 5.2 Host Management Page

After creation, host sees:

```
┌──────────────────────────────────────────┐
│ 🎉 Chukwu's Birthday Giveaway            │
│ MTN 1GB Data • 50 slots • No expiry      │
│                                          │
│ ████████████░░░░░░░░ 32/50 claimed       │
│                                          │
│ Link: subhero.com.ng/g/HERO2025ABC       │
│ [Copy Link] [Share WhatsApp] [Share IG]  │
│                                          │
│ [Download QR Code] [View Claims]         │
│                                          │
│ Status: 🟢 ACTIVE                        │
│ [Cancel Giveaway] (only if 0 claims)     │
└──────────────────────────────────────────┘
```

### 5.3 Claim Flow (Claimant — NO Account Required)

```
CLAIMANT OPENS subhero.com.ng/g/HERO2025ABC
         │
         ├── System checks giveaway validity:
         │     Is giveaway ACTIVE? → continue
         │     Is remaining_slots > 0? → continue
         │     Has expiry passed? → show closed page
         │
         ├── Sees claim page:
         │     "🎉 Chukwu's Birthday Giveaway"
         │     "Claim your FREE 1GB MTN Data"
         │     "18 of 50 slots remaining"
         │     [Phone number input]
         │     [Claim My Free Data] button
         │
         ├── Enters Nigerian phone number
         │
         ├── System validates:
         │     Nigerian format (07x, 08x, 09x / +234)
         │     Not already claimed this giveaway
         │     IP rate limit not exceeded
         │     Cloudflare Turnstile passes (bot check)
         │
         ├── Shows pending screen:
         │     "Sending your 1GB data..."
         │     "This usually takes under 10 seconds"
         │     [animated loading indicator]
         │     [HTMX polling every 3 seconds for status]
         │
         ├── CheapDataHub API delivers data/airtime
         │
         └── Shows success screen:
               "✅ Your 1GB MTN Data has been sent!"
               "Check your phone — delivery is instant"
               [CREATE ACCOUNT CTA — see section 10.1]
```

### 5.4 Slot Management Logic

```
Slot reservation is ATOMIC — uses SELECT FOR UPDATE:

When a claim is submitted:
  1. Lock the Giveaway row (SELECT FOR UPDATE)
  2. Check remaining_slots > 0
  3. Create GiveawayClaim (status=PENDING)
  4. Increment claimed_slots
  5. If claimed_slots == total_slots: set status=COMPLETED
  6. COMMIT
  7. Call CheapDataHub API (outside atomic)

If API delivery fails after 3 retries:
  1. Lock Giveaway row again
  2. Decrement claimed_slots
  3. If status was COMPLETED: revert to ACTIVE
  4. Update GiveawayClaim status=FAILED
  5. COMMIT
  (Slot is released back — another person can claim it)
```

### 5.5 Expiry & Refund Logic

```
Celery Beat runs every hour:
  Find all ACTIVE giveaways where expires_at < now()
  For each:
    unclaimed = total_slots - claimed_slots
    if unclaimed == 0: mark COMPLETED, done
    if unclaimed > 0:
      refund = unclaimed × amount_per_slot
      Credit refund to host wallet (atomic)
      Create REFUND WalletTransaction
      Mark giveaway EXPIRED
      SMS host: refund amount + claims summary

Host cancels giveaway (0 claims only):
  Full refund → host wallet
  Giveaway marked CANCELLED

Giveaway fully claimed:
  Marked COMPLETED immediately
  SMS host: "🎉 All slots claimed!"
  No refund needed (all funds spent on delivery)
```

---

## 6. Data Architecture

### 6.1 Models

```python
class Giveaway(models.Model):
    id              = UUIDField(primary_key=True)
    host            = ForeignKey(User)
    slug            = CharField(max_length=20, unique=True)
    title           = CharField(max_length=100)
    giveaway_type   = CharField()    # DATA | AIRTIME
    network         = CharField()    # mtn|airtel|glo|9mobile
    plan_id         = CharField()    # VTUPlan ID (data only)
    amount_per_slot = DecimalField() # ₦ per person
    total_slots     = IntegerField()
    claimed_slots   = IntegerField(default=0)
    total_locked    = DecimalField() # escrowed from host wallet
    total_spent     = DecimalField() # actual API cost so far
    status          = CharField()    # ACTIVE|COMPLETED|EXPIRED|CANCELLED
    qr_code_path    = CharField()    # path to branded QR PNG
    expires_at      = DateTimeField(null=True)
    created_at      = DateTimeField(auto_now_add=True)

    @property
    def remaining_slots(self):
        return self.total_slots - self.claimed_slots

    @property
    def claim_url(self):
        return f'https://subhero.com.ng/g/{self.slug}'

    @property
    def is_claimable(self):
        return (self.status == 'ACTIVE'
                and self.remaining_slots > 0
                and (not self.expires_at
                     or self.expires_at > now()))


class GiveawayClaim(models.Model):
    id            = UUIDField(primary_key=True)
    giveaway      = ForeignKey(Giveaway, related_name='claims')
    phone_number  = CharField(max_length=15)
    amount        = DecimalField()   # what they received
    provider_ref  = CharField()      # CheapDataHub order ID
    status        = CharField()      # PENDING|SUCCESS|FAILED
    ip_address    = GenericIPAddressField()
    claimed_at    = DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['giveaway', 'phone_number']]
        # DB-level enforcement: one claim per phone per giveaway


class GiveawayEscrow(models.Model):
    giveaway        = OneToOneField(Giveaway)
    wallet          = ForeignKey(Wallet)
    locked_amount   = DecimalField()         # total deducted at creation
    released_amount = DecimalField(default=0) # refunded for unused slots
    debit_reference = CharField()            # WalletTransaction ref
    created_at      = DateTimeField(auto_now_add=True)
```

### 6.2 New WalletTransaction Types

Add to `txn_type` choices in `WalletTransaction`:

```
GIVEAWAY_LOCK     → Host creates giveaway — funds locked
GIVEAWAY_REFUND   → Unused slots refunded to host
```

These integrate with the existing transaction ledger and appear in:
- Host's SubHero transaction history
- Admin panel transaction log
- Live system logs

---

## 7. Security Architecture

### 7.1 Threat Matrix

| Threat | Attack Description | Mitigation |
|---|---|---|
| Slot Exhaustion | Bot submits 500 requests simultaneously to drain all slots | SELECT FOR UPDATE atomic lock — only one transaction modifies claimed_slots at a time |
| Phone Abuse | Same person uses multiple phone numbers to claim multiple times | Per-phone unique_together DB constraint per giveaway — rejected at DB level |
| IP Farming | One person uses 50 different phones at same IP | Redis rate limit: max 10 claims per IP per day across ALL giveaways |
| Bot Farming | Automated scripts submitting fake numbers | Cloudflare Turnstile (free invisible challenge) on claim form |
| Slug Enumeration | Attacker guesses slugs to find active giveaways | 10-char random alphanumeric slug = 36^10 = 3.6 trillion combinations |
| Giveaway Link Scraping | Bot finds giveaway links and drains slots | Rate limit: max 3 claim attempts per IP per giveaway per hour |
| Balance Manipulation | Client sends tampered total_cost in creation form | Server always calculates: cost = VTUPlan.subhero_price × slots. Client value never trusted. |
| Concurrent Double-Spend | Host creates two giveaways simultaneously depleting wallet | SELECT FOR UPDATE on wallet at giveaway creation — same pattern as all wallet debits |
| Host Data Exposure | Claimant inspects page source to see host wallet info | Claim page template exposes ZERO financial data about host — only giveaway type and remaining slots |
| Fake Delivery Claim | Host claims delivery happened when it didn't to justify no refund | GiveawayClaim records every attempt with provider_ref — admin can verify against CheapDataHub dashboard |

### 7.2 Rate Limiting Implementation

```python
# Redis keys for giveaway rate limiting

# Per IP per giveaway: max 3 attempts per hour
f"ga_attempt:{giveaway_id}:{ip_address}"  TTL: 3600s  max: 3

# Per IP per day across all giveaways: max 10 claims
f"ga_daily:{ip_address}:{date.today()}"   TTL: 86400s max: 10

# Per phone per giveaway: enforced at DB level (unique_together)
# No Redis key needed — DB constraint handles this
```

### 7.3 Claim Page Security Rules

```
- NO CSRF token required (public page — no session)
- Cloudflare Turnstile on every claim form submit
- Phone number validated with Nigerian regex server-side
  Pattern: ^(0[7-9][0-1]\d{8}|\+234[7-9][0-1]\d{8})$
- All normalised to 0XX format before storage
- IP logged on every claim attempt (success or fail)
- User agent logged for bot pattern detection
- Claim page never reveals: host identity, total_locked,
  host wallet balance, number of failed claims
- Only shows: title, type, amount/plan, remaining slots
```

---

## 8. Growth & Acquisition Engine

This section documents SubHero's giveaway feature as a growth system, not just a product feature.

### 8.1 The Acquisition Flywheel

```
         ┌─────────────────────────────────┐
         │                                 │
         ▼                                 │
   [Host creates giveaway]                 │
         │                                 │
         │ Shares link to their audience   │
         ▼                                 │
   [50 claimants open link]                │
         │                                 │
         │ 50 see SubHero brand            │
         │ 50 receive real value           │
         ▼                                 │
   [Success page conversion CTA]           │
         │                                 │
         │ ~20–30% create account          │
         │ ~10–15% fund wallet             │
         │ ~5–10% run their own giveaway   │
         │                                 │
         └─────────────────────────────────┘
                    (loop repeats with
                     new hosts created)
```

### 8.2 Acquisition Channels Created by This Feature

**Channel 1 — WhatsApp Groups**
The #1 distribution channel in Nigeria. A single giveaway link dropped in a 500-person WhatsApp group generates 500 impressions instantly. No ad spend. No targeting. Just organic reach inside trusted social circles.

**Channel 2 — Instagram & TikTok Stories**
Creators share the QR code as a story. Followers screenshot and scan. SubHero QR code = SubHero logo visible in every screenshot shared across platforms.

**Channel 3 — Twitter/X Posts**
"First 100 people to claim this link get free 1GB MTN data → subhero.com.ng/g/HERO2025ABC" — this style of post goes viral regularly on Nigerian Twitter.

**Channel 4 — University WhatsApp Groups**
Student associations running giveaways. Nigeria has ~170 federal and state universities with thousands of student WhatsApp groups. One student union giveaway = hundreds of student leads.

**Channel 5 — Church & Religious Groups**
Nigerian churches are large, organised communities with existing digital infrastructure (WhatsApp, Telegram). A Pastor running weekly data giveaways reaches hundreds weekly.

**Channel 6 — Business Customer Groups**
SMEs sharing giveaway links with their customer base as a loyalty reward. Their customers become SubHero's customers.

### 8.3 Conversion Rate Assumptions (Conservative)

| Stage | Drop-off | Conversion |
|---|---|---|
| Claimants who open link | 100% | Baseline |
| Complete claim (enter phone) | 70% | Friction from rate limits, bot check |
| See success + CTA page | 100% of claimers | All see it |
| Click "Create Account" | 25% | Warm lead — already received value |
| Complete registration | 60% of clickers | Pre-filled phone reduces friction |
| Fund wallet (within 7 days) | 40% of registered | Strong intent users |
| Make first purchase | 70% of funded | Already motivated |

**Net: 1 giveaway with 50 slots →**
- 35 claims delivered
- 8–9 new SubHero registrations
- 3–4 funded wallets
- 2–3 paying customers
- Potential: 1 new giveaway host from the batch

### 8.4 Referral Credit Integration (Phase 2)

When a claimant creates an account from a giveaway success page:
- Store `source_giveaway_slug` on the new User record
- When they fund their wallet for the first time:
  - Credit host ₦100 (referral reward)
  - Credit new user ₦50 (welcome bonus)
- Track: "This giveaway generated X new paying users"
- Show this to host in their giveaway analytics
- This incentivises hosts to run giveaways repeatedly

---

## 9. Brand Advertising Engine

Every giveaway is free SubHero advertising. This section documents exactly where and how SubHero brand appears in the giveaway lifecycle — and why it matters.

### 9.1 Brand Touchpoints Per Giveaway

```
TOUCHPOINT 1 — The Shareable Link
subhero.com.ng/g/HERO2025ABC
  - SubHero domain in every link
  - Shared on WhatsApp, Instagram, Twitter, Telegram
  - Every person who sees the link sees "subhero.com.ng"
  - When WhatsApp generates a link preview:
      Show: SubHero logo + "🎁 Free Data Giveaway"
  - Implement Open Graph meta tags on claim page:
      og:title   = "🎉 {title} — Claim Free Data on SubHero"
      og:image   = SubHero giveaway banner image
      og:description = "{remaining} slots remaining. No account needed."

TOUCHPOINT 2 — The QR Code
  - Custom green QR code with SubHero logo in center
  - Every screenshot of the QR carries the SubHero logo
  - Shared on Instagram stories, TikTok videos, WhatsApp
  - Physically printable — can appear on flyers, posters
  - This is free OOH (out-of-home) advertising

TOUCHPOINT 3 — The Claim Page
  - URL: subhero.com.ng/g/{slug}
  - SubHero logo top left
  - "Powered by SubHero" footer
  - Nigerian green branding throughout
  - Loads fast (under 2 seconds on 3G)
    = positive brand impression even on slow networks

TOUCHPOINT 4 — The Delivery SMS
  After successful claim, Termii sends:
  "You've received [1GB MTN Data] from [Host Name]
   via SubHero. Buy your own cheap data at subhero.com.ng"
  - Cost: ₦17 per SMS
  - SubHero domain appears in every claimant's SMS inbox
  - This is inbox advertising — highest attention channel

TOUCHPOINT 5 — The Success Page
  - Full-page SubHero branded experience
  - Claimant's most positive emotional moment
    (they just got something free)
  - SubHero brand = associated with receiving value
  - This is the strongest brand impression possible:
    positive emotion + brand name = brand association

TOUCHPOINT 6 — The Shareable Receipt Card
  After giveaway ends, host gets a card:
  ┌──────────────────────────┐
  │  🎉 My Birthday Giveaway │
  │  50/50 slots claimed     │
  │  50GB data given away    │
  │  ₦10,000 in love shared  │
  │  ──────────────────────  │
  │  [SubHero Logo]          │
  │  Hosted on SubHero       │
  └──────────────────────────┘
  Hosts share this on their Instagram/Twitter as proof.
  Every share = free organic SubHero content post.

TOUCHPOINT 7 — The WhatsApp Link Preview
  When the giveaway URL is pasted on WhatsApp:
  Shows: SubHero giveaway card preview image
  Headline: "🎁 Free 1GB MTN Data — 18 slots left"
  Subtext: "Powered by SubHero"
  This generates curiosity and clicks from everyone who
  sees it in the group — not just the people who claim.
```

### 9.2 Estimated Free Brand Impressions Per Giveaway

For a typical 50-slot giveaway shared by a Nigerian with 1,000 followers:

| Channel | Impressions |
|---|---|
| WhatsApp group members who see link | 200–500 |
| Instagram story views | 300–800 |
| Twitter impressions | 100–2,000 |
| People who open claim page | 50–150 |
| Claimants who read delivery SMS | 35–50 |
| People who see host's receipt card post | 300–800 |
| **Total per giveaway** | **985–4,300 impressions** |

All of these are **free** — the host paid for the giveaway, not the advertising.

### 9.3 The QR Code Virality Play

A custom SubHero QR code is uniquely powerful because:

1. **It's visual** — can be embedded in YouTube thumbnails, Instagram posts, stories, TikToks
2. **It's physical** — hosts can print it on flyers, banners, business cards
3. **It's branded** — the SubHero green logo in the center is unmistakable
4. **It's curiosity-inducing** — a QR code in a post creates FOMO ("what does this unlock?")
5. **It's shareable as an image** — one screenshot becomes its own piece of content

Build the QR code to be high resolution (minimum 600×600px) so it's printable. Include a tagline below the QR: "Scan to claim your free data — Powered by SubHero"

### 9.4 Open Graph Implementation

Every claim page (`/g/{slug}/`) must have these meta tags for rich WhatsApp/Twitter previews:

```html
<meta property="og:title"
      content="🎁 {{ giveaway.title }} — Claim Free {{ giveaway.giveaway_type|title }}">
<meta property="og:description"
      content="{{ giveaway.remaining_slots }} slots remaining.
               No account needed — just enter your number.">
<meta property="og:image"
      content="https://subhero.com.ng/static/img/giveaway-og.png">
<meta property="og:url"
      content="https://subhero.com.ng/g/{{ giveaway.slug }}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title"
      content="🎁 {{ giveaway.title }}">
<meta name="twitter:description"
      content="{{ giveaway.remaining_slots }} free slots left on SubHero">
```

The `giveaway-og.png` is a static branded image (green background, SubHero logo, "Free Data Giveaway" text) — one image used for all giveaway link previews.

---

## 10. Lead Conversion Funnels

### 10.1 The Success Page Conversion Architecture

The success page is the highest-value page in the entire giveaway feature. The claimant is at peak positive emotion — they just received something free. This is the optimal moment to present the SubHero value proposition.

```
SUCCESS PAGE LAYOUT (Mobile — 360px):

┌─────────────────────────────────┐
│ ✅ (animated green checkmark)    │
│                                 │
│ Your 1GB MTN Data               │
│ has been sent!                  │
│                                 │
│ Check your phone —              │
│ delivery is instant ⚡          │
│                                 │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                 │
│ 💸 Buy cheap data for yourself  │
│                                 │
│ MTN 1Gb = ₦330                   │
│ Airtel 2gb = ₦600                │
│ GLO  5gb = ₦1,100                │
│ 9mobile 2gb = ₦600             │
│                                 │
│ + Run your OWN giveaway         │
│ + Buy Data and Airtime and      |
|  also manage your socials       │
│                                 │
│ [Create Free Account →]         │
│ Takes 2 minutes • │
│                                 │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                 │
│ "Already saving on data         │
│  since I joined SubHero"        │
│  — Tunde, Lagos ⭐⭐⭐⭐⭐          │
│                                 │
│ [Maybe Later]                   │
└─────────────────────────────────┘
```

Key principles:
- **Show real prices immediately** — seeing ₦350 for 1GB when they probably pay ₦400+ is compelling
- **Pre-fill their phone number** in the registration link — one less field
- **Social proof below the CTA** — not above (doesn't distract from the button)
- **"Maybe Later" is tiny** — deprioritise without hiding (dark patterns avoided)
- **No login friction** — "Create Free Account" goes to registration, not login

### 10.2 Pre-fill Registration from Giveaway

```python
# In claim_success view:
def claim_success(request, slug):
    phone = request.GET.get('phone', '')
    register_url = f'/auth/register/?phone={phone}&source=giveaway&ref={slug}'
    return render(request, 'giveaway/success.html', {
        'register_url': register_url,
        'phone': phone,
    })

# In accounts/views.py register view:
def register(request):
    phone = request.GET.get('phone', '')
    source = request.GET.get('source', '')
    ref_slug = request.GET.get('ref', '')
    # Pre-populate phone field
    # Store source and ref_slug for attribution
```

### 10.3 The "Host Your Own" Viral Loop

On the success page, after the primary CTA, show a secondary hook:

```
┌─────────────────────────────────┐
│ 🎁 Loved this giveaway?         │
│                                 │
│ Run one for YOUR people.        │
│ It takes 2 minutes to set up.   │
│                                 │
│ [See how it works →]            │
└─────────────────────────────────┘
```

"See how it works" goes to a **public explainer page** (no login required) that shows how giveaways work and ends with "Create your account to get started."

### 10.4 The "Almost Out" Urgency Trigger

When remaining slots drop to 20% of total:

```
Claim page headline changes to:
"⚡ Only 8 slots left! Claim yours now"
(CSS class swap via HTMX when server returns low_slots=True)
```

This is not fake urgency — it's accurate. It creates genuine FOMO and increases completion rate for people who opened the link but haven't submitted yet.

### 10.5 Landing Page Integration

On the SubHero landing page (`/`), add a live social proof section:

```
┌─────────────────────────────────┐
│ 🎁 Live on SubHero right now    │
│                                 │
│  "Emeka's Graduation Giveaway"  │
│   MTN 1GB • 12 slots left       │
│   [Claim Now →]                 │
│                                 │
│  "Sunday Blessing ❤️"           │
│   Airtel 500MB • 34 slots left  │
│   [Claim Now →]                 │
│                                 │
│ (Only shows public giveaways    │
│  where host opted in to listing)│
└─────────────────────────────────┘
```

This is a **reason to visit SubHero even without being invited** — people browse for active giveaways they can claim. This creates organic direct traffic.

---

## 11. Retention Mechanics

### 11.1 Host Retention

**After first giveaway:**
- SMS: "Your giveaway is complete! 🎉 Ready to run another? Your audience loved it."
- Dashboard badge: "Giveaway Host 🎁" shown on profile
- If referral credits earned: "3 people joined SubHero from your giveaway! You've earned ₦300 credit."

**Recurring use cases to target:**
- "Birthday Month" reminder — if host ran a birthday giveaway, prompt them 11 months later
- "You ran a giveaway 30 days ago — your followers might be ready for another one"
- Seasonal prompts: Sallah, Christmas, New Year, Valentine's Day

**Milestone rewards (Phase 2):**
- 5 giveaways hosted → "Super Host 🌟" badge
- 10 giveaways → permanent 1% extra discount on VTU for giveaways
- 500 total slots given → "SubHero Legend 🏆" profile badge

### 11.2 Claimant Retention

The claimant who registers is SubHero's best kind of new user — they have **already experienced the product working** before they even signed up. Their trust level is high.

Within 24 hours of registration send:
- SMS: "Welcome to SubHero, [Name]! Fund your wallet and buy 1GB MTN data for just ₦350. 3x cheaper than dialling *131#."

Within 7 days if no wallet funding:
- SMS: "Your SubHero wallet is empty. Top up with as little as ₦100 and buy data instantly. subhero.com.ng"

First purchase prompt:
- After funding: immediately show VTU quick-buy on dashboard — reduce time-to-first-purchase to under 60 seconds

### 11.3 The Shareable Receipt Card

After a giveaway ends (COMPLETED or EXPIRED), generate a shareable receipt card image:

```
Design: 1080x1080px (Instagram-ready)
Background: SubHero green gradient
Content:
  - 🎉 emoji large
  - "{giveaway.title}"
  - "{claimed_slots} people received free {type}"
  - "{total_amount_given} given away"
  - SubHero logo bottom center
  - "Host your own at subhero.com.ng"
```

Generated with Pillow (same dependency as QR code).
Downloaded as PNG from host's giveaway management page.
Host shares on Instagram, Twitter, WhatsApp stories.
Every share = unpaid SubHero content post.

---

## 12. Revenue Model

### 12.1 Direct Revenue Per Giveaway

SubHero earns its standard VTU margin on every delivery:

```
Example: 50-slot MTN 1GB giveaway

  Host pays SubHero:       50 × ₦350 = ₦17,500
  SubHero pays CheapDataHub: 50 × ₦228 = ₦11,400
  SubHero gross profit:      ₦6,100 per giveaway

  At 100 giveaways/month:  ₦610,000/month from giveaways alone
  At 500 giveaways/month:  ₦3,050,000/month
```

### 12.2 Indirect Revenue — New User LTV

Each giveaway generates ~3–4 new paying users (conservative).
Each paying SubHero user spends an estimated ₦2,000–₦5,000/month.
Annual LTV per user: ₦24,000–₦60,000 in GMV.
SubHero margin on that GMV: 5–10% = ₦1,200–₦6,000/year per acquired user.

**Giveaway as CAC (Customer Acquisition Cost):**
- Cost to SubHero per giveaway: ₦0 (host pays)
- New users acquired per giveaway: 3–4
- CAC via giveaway: ₦0

This is the most important number. SubHero acquires users for free via giveaways.

### 12.3 Phase 2 Monetisation Layers

**Boost Fee (₦500 per giveaway):**
Host pays ₦500 extra to have their giveaway listed on the public `/giveaways/` discovery page. This puts it in front of every SubHero visitor. Value: significantly more claimants = more exposure for host.

**Business Giveaway Plan:**
Dedicated plan for SMEs and brands: custom sender name on delivery SMS, analytics dashboard, priority support, scheduled giveaways. Monthly subscription or per-giveaway fee.

**Bulk Slot Discount (Host Incentive):**
- 1–50 slots: standard price
- 51–200 slots: 2% off per slot
- 200+ slots: 4% off per slot

This encourages larger giveaways (more exposure for SubHero) while rewarding power users.

---

## 13. Page Inventory & UX Specification

### 13.1 Page List

| Page | URL | Auth Required | Purpose |
|---|---|---|---|
| Create Giveaway | /giveaway/create/ | Yes | Host creates new giveaway |
| My Giveaways | /giveaway/mine/ | Yes | Host manages all giveaways |
| Giveaway Detail | /giveaway/{uuid}/ | Yes (host only) | Full stats + claims list |
| Claim Page | /g/{slug}/ | NO | Public claim page |
| Claim Pending | /g/{slug}/pending/ | NO | Processing state |
| Claim Status | /g/{slug}/status/ | NO | HTMX poll endpoint |
| Claim Success | /g/{slug}/success/ | NO | Success + CTA page |
| Giveaway Closed | /g/{slug}/closed/ | NO | Ended/expired state |
| Public Discovery | /giveaways/ | NO | Browse active public giveaways |
| How It Works | /giveaway/how-it-works/ | NO | Explainer for non-users |

### 13.2 Create Giveaway Page Spec

```
Layout: Single scrollable page — mobile first

SECTION 1 — Reward Type
  Toggle: [Data] [Airtime]
  Visual: pills with emoji (📶 Data | 📱 Airtime)

SECTION 2 — Network
  4 pill buttons: MTN (yellow) | Airtel (red)
                  Glo (green) | 9mobile (teal)
  Active state: filled pill with brand color

SECTION 3 — Plan/Amount
  If DATA:
    Scrollable plan cards (same component as VTU page)
    Shows: plan name + size + validity + price
    Selected: green left border
  If AIRTIME:
    Large amount input with ₦ prefix
    Quick amounts: ₦100 ₦200 ₦500 ₦1,000

SECTION 4 — Slots
  Number input: "How many people?"
  Minimum: 1, Maximum: 500
  Quick selectors: 10 | 25 | 50 | 100

SECTION 5 — Optional Settings
  Collapsible "More Options" section:
    Giveaway Title: text input (optional)
    Expiry: datetime picker (optional, min: 1 hour from now)

SECTION 6 — Cost Summary (sticky, always visible)
  ┌────────────────────────┐
  │ Amount per person: ₦350│
  │ Number of slots:    50 │
  │ ──────────────────── │
  │ Total Cost:     ₦17,500│
  │ Your Balance:   ₦25,000│
  │ After:          ₦7,500 │
  └────────────────────────┘
  Updates live as inputs change (Vanilla JS)

BOTTOM CTA (sticky):
  [Create Giveaway — ₦17,500] → triggers PIN sheet
```

### 13.3 Claim Page Spec

```
Layout: Minimal, distraction-free, fast-loading
Goal: Maximum claim completion rate

TOP: SubHero logo (small, top left)
     "Powered by SubHero" — not obtrusive

HERO SECTION:
  🎉 (large emoji)
  "{giveaway.title}"
  font: Bricolage Grotesque, 28px bold

  "Claim your FREE {plan_name or amount}" 
  e.g. "Claim your FREE 1GB MTN Data"
  font: DM Sans, 16px, muted color

  "{remaining_slots} of {total_slots} slots left"
  Visual slot bar: ██████░░░░ (progress bar)
  If slots < 20%: pulse animation on bar + "⚡ Almost gone!"

INPUT SECTION:
  Label: "Your Phone Number"
  Input: Large (52px height), inputmode="tel"
  Placeholder: "08012345678"
  Full-width on mobile

  [Cloudflare Turnstile — invisible mode]

SUBMIT BUTTON:
  "Claim My Free [1GB Data]" — full width, 52px
  Brand green, large font

FOOTER:
  "No account needed • Instant delivery"
  "This giveaway is powered by SubHero"
```

### 13.4 Claim Success Page Spec

```
TOP: Animated checkmark (SVG stroke animation, CSS only)
     ✅ 80px, green circle

HEADLINE: "Your {plan} has been sent!"
SUBTEXT: "Check your phone — delivery is usually instant"
PHONE SHOWN: "Sent to: 0801XXX5678" (partially masked)

DIVIDER

CONVERSION SECTION:
  Heading: "💸 Buy cheap data on SubHero"
  
  Mini price comparison:
  MTN 1GB ₦350  |  Airtel 2GB ₦650  |  GLO 5GB ₦1,200
  
  "Plus run giveaways, send money FREE, pay electricity bills"
  
  [Create Free Account →]
  Subtext: "Takes 2 minutes • No CAC needed"

SOCIAL PROOF:
  ⭐⭐⭐⭐⭐ "Tunde, Lagos"
  "Been using SubHero for 3 months.
   Saving ₦2,000+ every month on data."

SECONDARY LINK:
  [Maybe Later] — small, muted, at very bottom

TRACKING: UTM param on register link:
  /auth/register/?phone={phone}&utm_source=giveaway
  &utm_medium=claim_success&utm_campaign={slug}
```

### 13.5 QR Code Design Specification

```
Technical:
  Library: qrcode[pil] + pillow
  Size: 600×600px minimum (printable at 4x4 inches)
  Error correction: ERROR_CORRECT_H (30% can be obscured)
  Module drawer: RoundedModuleDrawer (rounded dots)
  Front color: RGB(0, 107, 62) — SubHero brand green
  Back color: RGB(255, 255, 255) — white

Logo overlay:
  File: static/img/subhero-qr-logo.png
  Size: 100×100px (center of 600px QR)
  Shape: Rounded square with white padding border
  Content: SubHero "SH" icon or logo mark

Below QR text (added via Pillow ImageDraw):
  "Scan to claim free data"
  "Powered by SubHero • subhero.com.ng"
  Font: DM Sans or system equivalent
  Color: #006B3E (brand green)

Output: PNG, saved to MEDIA_ROOT/giveaways/qr/{id}.png
```

---

## 14. API & Integration Spec

### 14.1 CheapDataHub Integration for Giveaways

Same service functions used for regular VTU purchases. No new API integration needed — giveaway claims call `buy_data()` and `buy_airtime()` from `vtu/services.py`.

The only difference: the `phone` parameter is the claimant's number (not the host's). This is passed directly from `GiveawayClaim.phone_number`.

### 14.2 Termii SMS for Giveaway Events

**Delivery confirmation to claimant:**
```
"You've received {plan_name} from {host.full_name} via SubHero.
 Buy your own cheap data at subhero.com.ng"
```
Sent after SUCCESS status on claim. Cost: ₦17 per SMS.

**Completion notification to host:**
```
"SubHero: 🎉 Your giveaway '{title}' is complete!
 {claimed}/{total} slots were claimed."
```

**Expiry + refund to host:**
```
"SubHero: Your giveaway '{title}' has ended.
 {claimed}/{total} slots claimed.
 ₦{refund_amount} refunded to your wallet."
```

### 14.3 QR Code Generation

```python
# giveaway/utils.py

import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers import RoundedModuleDrawer
from qrcode.image.styles.colormasks import SolidFillColorMask
from PIL import Image, ImageDraw, ImageFont
import os
from django.conf import settings


def generate_subhero_qr(claim_url: str, giveaway_id: str) -> str:
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=3,
    )
    qr.add_data(claim_url)
    qr.make(fit=True)

    img = qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=RoundedModuleDrawer(),
        color_mask=SolidFillColorMask(
            front_color=(0, 107, 62),
            back_color=(255, 255, 255)
        )
    )

    # Convert to PIL for logo overlay
    img = img.convert('RGB')
    img_w, img_h = img.size

    # Paste logo
    logo_path = os.path.join(settings.STATIC_ROOT,
                             'img', 'subhero-qr-logo.png')
    if os.path.exists(logo_path):
        logo = Image.open(logo_path).convert('RGBA')
        logo_size = int(img_w * 0.15)  # 15% of QR width
        logo = logo.resize((logo_size, logo_size),
                            Image.LANCZOS)
        pos = ((img_w - logo_size) // 2,
               (img_h - logo_size) // 2)
        img.paste(logo, pos, mask=logo)

    # Add text below QR
    final_img = Image.new('RGB', (img_w, img_h + 80),
                           (255, 255, 255))
    final_img.paste(img, (0, 0))
    draw = ImageDraw.Draw(final_img)
    draw.text((img_w // 2, img_h + 15),
              "Scan to claim free data",
              fill=(0, 107, 62),
              anchor='mt')
    draw.text((img_w // 2, img_h + 45),
              "Powered by SubHero • subhero.com.ng",
              fill=(107, 122, 153),
              anchor='mt')

    # Save
    output_dir = os.path.join(settings.MEDIA_ROOT,
                              'giveaways', 'qr')
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir,
                               f'{giveaway_id}.png')
    final_img.save(output_path, 'PNG', dpi=(300, 300))

    return f'giveaways/qr/{giveaway_id}.png'
```

---

## 15. Admin Panel Requirements

### 15.1 New Admin Page: Giveaways `/subhero-hq/giveaways/`

**Table columns:**
- ID (first 8 chars of UUID)
- Host (name + phone, links to user detail)
- Title
- Type (DATA/AIRTIME badge)
- Network
- Slots (claimed/total)
- Total Locked (₦)
- Total Spent on API (₦)
- SubHero Profit (locked - spent - refunded)
- Status badge (ACTIVE/COMPLETED/EXPIRED/CANCELLED)
- Created At
- Actions

**Filters:**
- Status: All | Active | Completed | Expired | Cancelled
- Type: All | Data | Airtime
- Network: All | MTN | Airtel | Glo | 9mobile
- Date range

**Admin Actions:**
- Force Expire: immediately expire a giveaway and trigger refund
- Force Refund: manually refund unclaimed escrow to host
- View All Claims: paginated list of every claim for that giveaway
- Suspend Giveaway: pause claims (abuse investigation)

### 15.2 New Dashboard Metrics

Add to `/subhero-hq/` dashboard:

```
Total Giveaways Hosted (all time)
Active Giveaways Right Now
Total Claims Delivered (all time)
Total Giveaway Revenue (all time)
New Users via Giveaway (Phase 2 — when source tracking live)
```

### 15.3 New System Log Events

```python
# In giveaway creation:
syslog('INFO', 'VTU',
       f'Giveaway created — host:{host.phone} '
       f'slug:{slug} type:{type} slots:{slots} '
       f'locked:₦{total_locked}')

# In claim delivery success:
syslog('SUCCESS', 'VTU',
       f'Giveaway claim delivered — '
       f'phone:{phone} slug:{slug} plan:{plan}')

# In claim delivery failure:
syslog('ERROR', 'VTU',
       f'Giveaway claim FAILED — '
       f'phone:{phone} slug:{slug} '
       f'retries_exhausted:True')

# In expiry refund:
syslog('INFO', 'WALLET',
       f'Giveaway expired — slug:{slug} '
       f'claimed:{claimed}/{total} '
       f'refund:₦{refund_amount}')

# In giveaway complete:
syslog('SUCCESS', 'VTU',
       f'Giveaway COMPLETE — slug:{slug} '
       f'all {total} slots claimed')
```

---

## 16. Celery Tasks & Background Jobs

### 16.1 Task Registry

| Task | Trigger | Schedule |
|---|---|---|
| `process_giveaway_claim` | On claim submit | Immediate async |
| `notify_host_giveaway_complete` | When last slot claimed | Immediate async |
| `expire_giveaways` | Time-based | Every hour (Celery Beat) |
| `refund_giveaway_unused_slots` | On expiry detected | Immediate async (from expire task) |
| `generate_receipt_card` | When giveaway ends | Immediate async |

### 16.2 Add to CELERY_BEAT_SCHEDULE

```python
'expire-giveaways': {
    'task': 'giveaway.tasks.expire_giveaways',
    'schedule': crontab(minute=0),  # top of every hour
},
```

---

## 17. Metrics & Success Criteria

### 17.1 Feature Health Metrics (Admin Dashboard)

| Metric | Formula | Target (Month 1) |
|---|---|---|
| Giveaways Created | COUNT(Giveaway) | 50+ |
| Slots Delivered | COUNT(GiveawayClaim, status=SUCCESS) | 1,000+ |
| Claim Success Rate | SUCCESS / (SUCCESS+FAILED) | > 95% |
| Avg Claims per Giveaway | total_claims / total_giveaways | > 30 |
| Conversion Rate (claim→register) | new_users_from_giveaway / total_claims | > 20% |
| Host Repeat Rate | hosts with 2+ giveaways / total_hosts | > 30% |
| Avg Giveaway Size (₦) | AVG(total_locked) | > ₦5,000 |
| Refund Rate | refunded_slots / total_slots | < 20% |

### 17.2 Growth Metrics

| Metric | How to Measure | Target |
|---|---|---|
| New users from giveaways | UTM tracking on register URL | 30% of all new users |
| Funded users from giveaways | utm_source=giveaway + first_fund event | 40% of giveaway-acquired users |
| Giveaway-host revenue per month | SUM profit where triggered_by=giveaway | ₦500,000+ |
| Brand impressions per giveaway | Estimated from slots × 20 (conservative) | 1,000+ per giveaway |

### 17.3 Definition of Success (3 Months Post-Launch)

The giveaway feature is successful if:
1. It generates at least 30% of SubHero's new monthly registered users
2. Claim success rate stays above 95%
3. At least 30% of hosts run more than one giveaway
4. At least one viral giveaway (500+ claims) has been hosted
5. Admin has received zero fraud incidents caused by this feature

---

## 18. Phase 2 Giveaway Extensions

### 18.1 Public Giveaway Discovery Page

`/giveaways/` — shows all giveaways where host opted into public listing.

Sorted by: most recently created | most slots remaining | ending soon.

Creates organic direct traffic to SubHero — people browse for free things to claim, find SubHero. Natural virality mechanism.

### 18.2 Scheduled Giveaways

Host can create a giveaway now, set it to start at a future time.

Use case: "My birthday is Friday. I want to set up the giveaway now and have it go live at midnight."

Implementation: Add `starts_at` field to Giveaway. Celery Beat checks hourly for scheduled giveaways whose `starts_at` has passed.

### 18.3 Business Giveaway Dashboard

Dedicated analytics view for power hosts (agents/businesses):

- Total giveaways hosted
- Total people reached
- Total data/airtime given
- Estimated new SubHero users generated (Phase 2)
- Month-over-month trends
- Downloadable report PDF

### 18.4 Corporate Giveaway API

Allow businesses to integrate SubHero giveaways into their own apps via API:

```
POST /api/v1/giveaway/create/
Authorization: Bearer {api_key}
{
  "type": "data",
  "network": "mtn",
  "plan_id": "mtn_1gb_30days",
  "slots": 500,
  "webhook_url": "https://yourbusiness.com/giveaway-webhook"
}
```

Returns: `{slug, claim_url, qr_code_url}`

Use case: A fintech app wants to give free data to new sign-ups. They call SubHero's API per user. SubHero fulfils instantly.

### 18.5 Boost/Promote Feature

Host pays ₦500 to have their giveaway:
1. Listed on `/giveaways/` discovery page (top placement)
2. Shown in a "Featured Giveaway" banner on SubHero homepage
3. Included in a weekly "Active Giveaways" SMS to opted-in users

This is SubHero's first native advertising product.

### 18.6 Receipt Card Generator

Automated generation of a shareable 1080×1080px image after giveaway completion. Built with Pillow. Features:

- SubHero green gradient background
- Gold/white typography
- Stats: slots claimed, total given, type
- Host name (optional)
- SubHero logo and "subhero.com.ng"
- QR code to SubHero landing page

Downloadable from host's giveaway management page. Designed to be shared as an Instagram post or WhatsApp status.

---

## 19. Out of Scope (MVP)

These are explicitly NOT built in the first version of this feature:

- Bill payment giveaways (electricity token, cable TV) — Phase 2
- International numbers — Nigeria only (MVP)
- Giveaway analytics dashboard for hosts — Phase 2
- Scheduled/future giveaways — Phase 2
- Public discovery page — Phase 2
- Boosted/featured giveaways — Phase 2
- Corporate API — Phase 2
- Receipt card generator — Phase 2
- Guest claim without phone (e.g. email-based) — never (phone is core to VTU delivery)
- Referral credit for giveaway conversions — Phase 2 (when referral system built)
- Host-to-host giveaway challenges/competitions — Phase 3
- Crypto or dollar-denominated giveaways — Phase 3

---

*SubHero Giveaway PRD v1.0 — SubVerse © 2026 — Confidential — Internal Use Only*
