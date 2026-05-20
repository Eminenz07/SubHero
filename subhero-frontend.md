# SubHero — Frontend Design PRD
## Version 1.0 | Nigeria-First Mobile-First Web UI

---

## 1. Design Philosophy

SubHero's UI is inspired by Nigeria's most-loved fintech apps — OPay, PalmPay, and Kuda — but elevated into a premium, trustworthy brand that feels modern and distinctly Nigerian. The goal is a UI that feels as polished as a top-tier banking app but loads fast on a ₦100 MTN data plan.

**Core Principles:**
- **Mobile-First Always**: Design at 360px. Every layout decision starts from a phone screen.
- **Speed over Decoration**: No web fonts that require HTTP requests. No heavy animations. Delight through clean layout, not loading spinners.
- **Trust through Clarity**: Financial apps must feel safe. Use whitespace, clear hierarchy, and legible numbers to build confidence.
- **Nigerian Context**: Nigerians are visually sophisticated — they use OPay and PalmPay daily. SubHero must feel better, not cheaper.

---

## 2. Brand Identity

| Token | Value | Use |
|---|---|---|
| `--brand-primary` | `#006B3E` | Nav bar, active states, headers |
| `--brand-accent` | `#00C46A` | CTAs, success badges, highlights |
| `--brand-dark` | `#0A1628` | Page backgrounds (dark sections) |
| `--bg-page` | `#F5F7FA` | Main app background |
| `--bg-card` | `#FFFFFF` | All cards and modals |
| `--text-primary` | `#0A1628` | Headlines, amounts |
| `--text-secondary` | `#6B7A99` | Labels, placeholders |
| `--text-muted` | `#A0AABF` | Disabled states |
| `--danger` | `#E53E3E` | Errors, failed transactions |
| `--warning` | `#F6AD1E` | Pending states |
| `--success` | `#00C46A` | Completed transactions |
| `--border` | `#E8ECF4` | All dividers and input borders |

**Typography:**
- Display/Headings: `Bricolage Grotesque` (Google Fonts — load subset only)
- Body/UI: `DM Sans` (Google Fonts — load subset only)
- Numbers/Amounts: `DM Mono` (for balance display — monospace prevents layout shift)
- Fallback stack: `system-ui, -apple-system, sans-serif`

> ⚠️ PERFORMANCE RULE: Load only Latin subset. Use `font-display: swap`. Total font payload must not exceed 40KB.

---

## 3. Layout System

### 3.1 Mobile Viewport (Base — 360px to 767px)
```
┌─────────────────────┐  ← 360px min-width
│  Top App Bar        │  ← 56px fixed top (auth pages only)
│  (contextual)       │
├─────────────────────┤
│                     │
│  Main Content Area  │  ← Scrollable, padding: 0 16px
│                     │
│                     │
├─────────────────────┤
│  Bottom Navigation  │  ← 64px fixed bottom (authenticated pages)
└─────────────────────┘
```

### 3.2 Desktop (md: 768px+)
- Max content width: 480px centered (simulates phone app on desktop)
- Side padding increases to 24px
- Bottom nav stays — do not switch to top nav on desktop for user pages
- Admin panel only: full-width desktop layout with sidebar

### 3.3 Spacing Scale
```
4px   → xs  (tight internal spacing)
8px   → sm  (between related elements)
12px  → md  (input padding)
16px  → lg  (section spacing, card padding)
24px  → xl  (major section breaks)
32px  → 2xl (hero spacing)
```

---

## 4. Components

### 4.1 Bottom Navigation Bar
- 5 tabs: **Home · VTU · SMM · Wallet · Profile**
- 64px tall, white background, top border 1px `--border`
- Active tab: icon + label in `--brand-primary`, indicator dot above icon
- Inactive: icon + label in `--text-muted`
- Icons: Feather Icons SVG sprite (single HTTP request, cached)
- Touch target: each tab = full height × 20% width (≥ 48px width)
- NEVER use hover effects on bottom nav — assume touch

### 4.2 Service Quick-Action Grid
- 2×2 grid on dashboard (Data, Airtime, Electricity, Cable) + (SMM row below)
- Each tile: icon (48×48 SVG in colored circle) + label below
- Tile size: fluid — fills 50% of container width
- Background: white card with subtle shadow
- Tap state: scale(0.96) with 100ms transition

### 4.3 Wallet Balance Card
- Full width, `--brand-primary` to `--brand-dark` gradient background
- Balance in DM Mono, size 32px bold, white color
- "Show/Hide Balance" eye icon toggle (Vanilla JS)
- "Fund Wallet" + "Transfer" CTA buttons below balance
- Decorative: subtle radial gradient + noise texture overlay for depth

### 4.4 Transaction List Item
- Left: colored icon circle (green = credit, red = debit)
- Center: service name (bold, 14px) + date (12px, `--text-muted`)
- Right: amount (bold, `--success` or `--danger`) + status badge
- Height: 64px minimum touch target
- Divider: 1px `--border` between items (not full-width — indent 56px from left)
- NO table layout on mobile — always flex rows

### 4.5 Input Fields
- Height: 52px (prevents iOS auto-zoom at 16px font-size)
- Font-size: 16px minimum — non-negotiable (prevents zoom)
- Border: 1.5px `--border`, border-radius: 12px
- Focus: border-color `--brand-accent`, box-shadow 0 0 0 3px rgba(0,196,106,0.15)
- Label: above input, 12px, `--text-secondary`, font-weight 500
- Error: border-color `--danger`, red error text below at 12px

### 4.6 Primary CTA Button
- Full width on mobile
- Height: 52px, border-radius: 14px
- Background: `--brand-accent`, color: white
- Font: DM Sans 600, 16px
- Tap feedback: brightness(0.9) + scale(0.98) at 80ms
- Loading state: spinner replaces text (CSS-only, no library)
- Disabled: opacity 0.5, cursor not-allowed

### 4.7 PIN Entry
- 4 individual boxes (not a single input)
- Each box: 56×56px, border: 2px `--border`, border-radius: 12px, centered
- Active box: border-color `--brand-accent`
- Filled: shows bullet dot (●), not the digit
- Built entirely in Vanilla JS — no library
- On mobile: triggers numeric keyboard (inputmode="numeric")

### 4.8 Network Selector Tabs
- Horizontal scrollable pill tabs
- MTN (yellow) · Airtel (red) · Glo (green) · 9mobile (teal)
- Active: filled pill with network brand color, white text
- Each network has its official color as the active background
- Scrollable with no scrollbar visible (overflow-x: auto, scrollbar-width: none)

### 4.9 Status Badges
```
SUCCESS  → green background (#DCFCE7), green text (#16A34A), "Successful"
PENDING  → yellow background (#FEF9C3), yellow text (#A16207), "Pending"
FAILED   → red background (#FEE2E2), red text (#DC2626), "Failed"
```

### 4.10 Bottom Sheet Modal (for PIN, confirmations)
- Slides up from bottom (translateY animation, 250ms ease-out)
- Backdrop: rgba(0,0,0,0.5) fade in
- Sheet: white, border-radius 20px top corners only
- Drag handle: 4px × 40px gray pill at top center
- Used for: PIN confirmation, transfer confirmation, service confirmation

---

## 5. Page-by-Page Specification

### 5.1 Landing Page (/)
**Purpose:** Convert visitors to registered users. Must work without JS (SSR).

**Sections (top to bottom):**
1. **Hero** — Brand gradient background (dark green), large headline, subheadline, "Get Started Free" CTA + "Login" ghost button
2. **Wallet Balance Teaser** — Animated counter widget showing ₦ savings
3. **Services Grid** — 6 service tiles in a 3×2 grid (Data, Airtime, Electricity, Cable, SMM, P2P Transfer)
4. **Why SubHero** — 3 horizontal scroll cards (Instant Delivery, Zero Transfer Fees, Cheap Data)
5. **How it Works** — 3-step numbered list (Register → Fund → Purchase)
6. **Social Proof** — 3 user testimonial cards (horizontal scroll on mobile)
7. **Footer** — Logo, links, copyright

### 5.2 Login Page (/auth/login/)
- Minimal — logo top center, headline, phone + password fields, submit button
- "Forgot Password?" link below password field
- "Don't have an account? Register" at bottom
- No distractions — pure conversion focus

### 5.3 Register Page (/auth/register/)
- Full Name → Phone Number → Email → Password → Confirm Password
- Step indicator if split into steps (optional — single form is fine for MVP)
- Inline validation on blur (server-side errors shown on submit)

### 5.4 Dashboard (/dashboard/)
**Top section:**
- Greeting: "Good morning, Emi 👋" (DM Sans, 16px)
- Notification bell icon (top right, badge count)

**Wallet Card (full width):**
- Balance display with show/hide toggle
- "Fund Wallet" + "Send Money" buttons

**Quick Actions Grid (2×2):**
- Data · Airtime · Electricity · Cable TV

**SMM Section (horizontal scroll):**
- Instagram · TikTok · YouTube · Twitter pills

**Recent Transactions:**
- Last 5 transactions, "View All" link
- Each item as a transaction list item component

### 5.5 VTU Pages (/vtu/data/, /vtu/airtime/, etc.)
- Top: Network selector tabs (MTN, Airtel, Glo, 9mobile)
- Phone number input (auto-filled from profile, editable)
- Plan/Bundle selector: scrollable vertical list of plan cards
  - Each card: data size (bold) + validity + price (right-aligned)
  - Selected card: left border 3px `--brand-accent`, light green background tint
- "Continue" button pinned to bottom (position: sticky)
- Confirmation bottom sheet with PIN entry before submit

### 5.6 SMM Page (/smm/)
- Platform tabs: Instagram · TikTok · YouTube · Twitter · Telegram · Spotify
- Service cards: service name + description + price per 1000 + order button
- Order flow: target URL input → quantity slider/input → price preview → PIN confirm

### 5.7 Wallet Page (/wallet/)
- Wallet balance card (same as dashboard)
- "Your SubHero Account Number" card (virtual account details, copy button)
- "Fund Wallet" section: shows account number + bank name + copy buttons
- Tab: Transactions | Shows wallet-specific transaction history

### 5.8 P2P Transfer (/wallet/transfer/)
- Recipient phone number input
- "Search" → shows recipient name + avatar initial for confirmation
- Amount input (large, centered, ₦ prefix)
- Note/description field (optional)
- PIN confirmation bottom sheet
- Success screen: animated checkmark + summary card

### 5.9 Transaction History (/transactions/)
- Filter tabs: All · VTU · SMM · Transfer · Funding
- Date group headers: "Today", "Yesterday", "April 2026"
- Transaction list items
- Tap any item → Transaction detail bottom sheet

### 5.10 Profile & Settings (/profile/)
- Avatar circle (initials-based — no image upload in MVP)
- Full name + phone number (display only)
- Settings list: Change Password · Change PIN · About · Logout

---

## 6. Animation & Motion Rules

- Page transitions: fade in (opacity 0→1, 200ms) — CSS only
- Cards on dashboard load: staggered translateY(12px)→0 with animation-delay 0, 50ms, 100ms, 150ms
- Bottom sheet open: translateY(100%)→0, 250ms ease-out
- Success checkmark: SVG stroke-dashoffset animation (CSS)
- Balance counter on landing: requestAnimationFrame counter (Vanilla JS, <15 lines)
- Loading spinner: CSS border-top spinning keyframe, no GIF, no library
- ALL animations respect `prefers-reduced-motion: reduce`

---

## 7. Accessibility Rules

- Minimum color contrast: 4.5:1 for body text, 3:1 for large text
- All inputs have associated `<label>` elements
- Error messages linked to inputs via `aria-describedby`
- Focus rings visible on keyboard navigation (hidden for mouse/touch only via `:focus-visible`)
- Loading states announced via `aria-live="polite"` region
- All icons have `aria-label` or accompanying visible text

---

## 8. Performance Rules (Nigeria Network Constraints)

| Asset | Budget | Method |
|---|---|---|
| Total HTML per page | < 25KB | Django SSR, minimal markup |
| CSS (app.css purged) | < 15KB gzipped | Tailwind purge + manual CSS |
| JavaScript (app.js) | < 20KB | Vanilla JS only, no libraries |
| HTMX | 8KB | Already minimal |
| Google Fonts | < 35KB | Latin subset, font-display: swap |
| Images | < 30KB per page | WebP, lazy-loaded, compressed |
| **Total per page** | **< 150KB gzipped** | Target for 3G under 2 seconds |

**Banned:**
- Any CSS framework beyond Tailwind (no Bootstrap, no Material UI)
- Any JS framework or library (no jQuery, no Alpine, no Stimulus)
- Icon fonts (use SVG sprite only)
- Base64 encoded images inline
- Autoplay video or audio

---

## 9. Django Template Architecture

```
templates/
  base.html              ← Master layout: meta, CSS, fonts
  base_auth.html         ← Extends base — no bottom nav (login/register)
  base_app.html          ← Extends base — bottom nav, top bar
  components/
    wallet_card.html     ← Reusable balance card
    transaction_item.html ← Single transaction row
    bottom_nav.html      ← Bottom navigation bar
    pin_sheet.html       ← PIN entry bottom sheet
    service_tile.html    ← Quick action tile
    network_tabs.html    ← Network selector tabs
    status_badge.html    ← Status badge (success/pending/failed)
    toast.html           ← HTMX-swapped toast notification
  accounts/
    login.html
    register.html
    verify_otp.html
    set_pin.html
  dashboard/
    index.html
  vtu/
    data.html
    airtime.html
    electricity.html
    cable.html
  smm/
    index.html
    order.html
  wallet/
    index.html
    fund.html
    transfer.html
  transactions/
    index.html
    detail.html          ← HTMX partial for bottom sheet
  profile/
    index.html
```

---

## 10. HTMX Usage Patterns

```
<!-- Transaction list refresh without full page reload -->
<div hx-get="/transactions/partial/" hx-trigger="load" hx-target="#txn-list">

<!-- Recipient lookup on phone input blur -->
<input hx-get="/wallet/lookup/" hx-trigger="blur" hx-target="#recipient-preview">

<!-- Plan list refresh on network tab change -->
<button hx-get="/vtu/data/plans/?network=MTN" hx-target="#plans-list" hx-swap="innerHTML">

<!-- PIN form submission — no full reload -->
<form hx-post="/vtu/data/confirm/" hx-target="#result-area" hx-swap="outerHTML">

<!-- Toast notification slot (server pushes success/error) -->
<div id="toast-area" aria-live="polite"></div>
```

All HTMX requests return HTML fragments — never JSON. Server renders the partial directly.

---

*SubHero Frontend PRD v1.0 — SubVerse © 2026 — Internal Dev Use Only*
