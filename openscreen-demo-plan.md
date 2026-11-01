# OpenScreen Demo Plan: SubHero Giveaway Feature

## Request Summary
Create a polished demo video showing the SubHero viral giveaway feature:
- Host creates and funds a data/airtime giveaway from wallet escrow
- Host receives branded QR code and shareable claim link
- Recipients claim instantly with only their phone number (no account required)
- Host tracks live claims in real-time

## OpenScreen Setup Status
- **Skill installed:** `openscreen-demo` in `.agents/skills/openscreen-demo`
- **OpenScreen App:** Detected and verified at `C:\Program Files\Openscreen\Openscreen.exe`
- **MCP Server Configured:** Added `openscreen` to `~/.gemini/config/mcp_config.json` and `~/.gemini/antigravity-ide/mcp_config.json`
- **Next Session:** MCP tools (`startRecording`, `stopRecording`, `exportVideo`, `getFrames`, `getCurrentDocument`, `addZooms`, `addAnnotation`, etc.) will be active.

---

## Storyboard (Launch Demo: ~35-45 seconds, 16:9 1080p)

### Beat 1: The Hook (0s – 6s)
- **Visual:** The generated SubHero Giveaway receipt card with custom branding, QR code, and "MTN 1.0GB Data Giveaway".
- **Action:** Host views their newly launched giveaway with shareable URL and download card button.
- **Callout:** `Instant data & airtime giveaways` (large typewriter title)

### Beat 2: 10-Second Creation Flow (6s – 14s)
- **Visual:** The "Create Giveaway" page (`/giveaway/create/`).
- **Action:** Select "Data Giveaway", pick network "MTN", select plan "1.0GB SME", set slots "10", enter title "Weekend Boost 🎉", enter PIN to lock escrow.
- **Callout:** `Pick reward and lock slots` (pop callout)

### Beat 3: Branded Shareable Assets (14s – 22s)
- **Visual:** Host dashboard / Giveaway Detail page (`/giveaway/<slug>/detail/`).
- **Action:** Copy public link and preview the high-res branded receipt card ready for WhatsApp/Instagram status.
- **Callout:** `Share anywhere via link & QR` (pop callout)

### Beat 4: Zero-Friction Recipient Claim (22s – 32s)
- **Visual:** Recipient claim page (`/giveaway/claim/<slug>/`) in clean mobile viewport view.
- **Action:** Recipient pastes their phone number `0814 555 0192`, clicks "Claim 1GB Data Now", instant success modal fires with confetti and "Data Delivered!".
- **Callout:** `Recipients claim with zero signup` (pop callout)

### Beat 5: Real-time Host Tracker & Viral Loop (32s – 40s)
- **Visual:** Back to Host live tracker showing progress bar updating (1/10 Claimed) and recipient listed in real time.
- **Action:** Highlight real-time claim table and CTA "Create Your Own Giveaway".
- **Callout:** `Track claims live in real-time` (pop callout)

---

## Staging & Execution Guide for Next Session
1. **App Server:** Ensure Django dev server is running on `http://127.0.0.1:8000`.
2. **Seed Data:** 
   - Ensure an authenticated host user with sufficient wallet balance (e.g. ₦10,000) and transaction PIN.
   - Active VTU plans loaded (MTN, Airtel, etc.).
3. **Capture Mode:**
   - Launch clean window (`--window-size=1600,1000`).
   - Call `startRecording` targeting the app window.
   - Execute the 5 storyboard beats with smooth, deliberate pacing (~1.5s pauses on key actions).
   - Call `stopRecording(title="SubHero Giveaway Feature Launch")`.
4. **Editing via MCP Document Tools:**
   - `setAspectRatio("16:9")`
   - `addTrims` to eliminate any dead time at start/finish.
   - `addZooms` on key interaction points (PIN input, QR code modal, claim button, live progress bar).
   - `addAnnotation` for beat callouts.
   - `exportVideo` to `demo/subhero-giveaway-demo.mp4` (1080p).
   - Validate frames with `getFrames`.
