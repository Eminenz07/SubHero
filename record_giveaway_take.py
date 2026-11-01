"""
SubHero Giveaway Feature — Demo Recording Script (Take 2)
=========================================================
Strategy:
  1. Use /demo-login/ endpoint (DEBUG only) to auto-auth the demo user
  2. Navigate to /giveaway/create/ — already authenticated
  3. Fill form with animated typing (AIRTIME mode — simpler, no plan_id needed)
  4. Submit → capture redirect URL → extract slug
  5. Record all 5 beats of the storyboard
"""

import asyncio
import json
import base64
import os
import time
import aiohttp
import urllib.request

TARGET_DIR = r"c:\Users\Eminence\Documents\SubHero\demo\frames"
DEMO_DIR   = r"c:\Users\Eminence\Documents\SubHero\demo"
os.makedirs(TARGET_DIR, exist_ok=True)
os.makedirs(DEMO_DIR,   exist_ok=True)

BASE = "http://127.0.0.1:8000"

async def run_demo():
    # ── Discover browser CDP target ──────────────────────────────────────────
    res = urllib.request.urlopen("http://127.0.0.1:9222/json").read()
    targets = json.loads(res)
    page_target = next(
        (t for t in targets if t.get("type") == "page"),
        None
    )
    if not page_target:
        raise RuntimeError("No Chrome page target found. Is Chrome running with --remote-debugging-port=9222?")

    ws_url = page_target["webSocketDebuggerUrl"]
    print(f"[CDP] Connected to: {ws_url}")

    frame_idx = 0

    async with aiohttp.ClientSession() as http_session:
        async with http_session.ws_connect(ws_url, max_msg_size=100 * 1024 * 1024) as ws:
            msg_id = 1

            async def send(method, params=None):
                nonlocal msg_id
                cmd = {"id": msg_id, "method": method, "params": params or {}}
                msg_id += 1
                await ws.send_json(cmd)
                while True:
                    r = await ws.receive_json()
                    if r.get("id") == cmd["id"]:
                        return r.get("result", {})

            async def snap():
                nonlocal frame_idx
                r = await send("Page.captureScreenshot", {"format": "jpeg", "quality": 90})
                path = os.path.join(TARGET_DIR, f"frame_{frame_idx:05d}.jpg")
                with open(path, "wb") as f:
                    f.write(base64.b64decode(r["data"]))
                frame_idx += 1

            async def hold(seconds, fps=15):
                n = int(seconds * fps)
                gap = 1.0 / fps
                for _ in range(n):
                    t0 = time.time()
                    await snap()
                    await asyncio.sleep(max(0, gap - (time.time() - t0)))

            async def js(expr):
                r = await send("Runtime.evaluate", {
                    "expression": expr,
                    "awaitPromise": True,
                    "returnByValue": True
                })
                return r.get("result", {}).get("value")

            async def navigate(url, settle=2.5):
                print(f"[NAV] {url}")
                await send("Page.navigate", {"url": url})
                # Wait for load event
                await asyncio.sleep(settle)

            async def type_into(selector, text, delay=0.055):
                """Type text character by character for a natural typing effect."""
                for i in range(1, len(text) + 1):
                    sub = json.dumps(text[:i])
                    await js(
                        f"(function(){{"
                        f"  var el = document.querySelector({json.dumps(selector)});"
                        f"  if(el){{ el.value = {sub}; el.dispatchEvent(new Event('input',{{bubbles:true}})); }}"
                        f"}})();"
                    )
                    await snap()
                    await asyncio.sleep(delay)

            async def set_field(selector, value):
                await js(
                    f"(function(){{"
                    f"  var el = document.querySelector({json.dumps(selector)});"
                    f"  if(el){{ el.value = {json.dumps(value)}; el.dispatchEvent(new Event('input',{{bubbles:true}})); el.dispatchEvent(new Event('change',{{bubbles:true}})); }}"
                    f"}})();"
                )

            async def smooth_scroll(from_y, to_y, steps=20, fps=15):
                sign = 1 if to_y > from_y else -1
                step_px = abs(to_y - from_y) // steps
                cur = from_y
                while (sign > 0 and cur < to_y) or (sign < 0 and cur > to_y):
                    cur += sign * step_px
                    cur = min(cur, to_y) if sign > 0 else max(cur, to_y)
                    await js(f"window.scrollTo(0, {cur})")
                    await snap()
                    await asyncio.sleep(1.0 / fps)

            # ── Enable Page & Set viewport ────────────────────────────────────
            await send("Page.enable")
            await send("Emulation.setDeviceMetricsOverride", {
                "width": 430,
                "height": 932,
                "deviceScaleFactor": 2,
                "mobile": True
            })

            # ──────────────────────────────────────────────────────────────────
            # BEAT 0: Auto-login via /demo-login/ (DEBUG view)
            # ──────────────────────────────────────────────────────────────────
            print("\n=== BEAT 0: Auto-login ===")
            await navigate(f"{BASE}/demo-login/?next=/giveaway/create/", settle=3.0)
            current_url = await js("window.location.href")
            print(f"[URL] After login: {current_url}")

            # If still on login page, something went wrong
            if "login" in current_url.lower():
                raise RuntimeError(f"Auto-login failed! Still at: {current_url}")

            # ──────────────────────────────────────────────────────────────────
            # BEAT 1: Show the Create Giveaway form
            # ──────────────────────────────────────────────────────────────────
            print("\n=== BEAT 1: Create Giveaway form ===")
            await navigate(f"{BASE}/giveaway/create/", settle=2.5)
            await hold(2.0)   # Show form for 2s

            # ──────────────────────────────────────────────────────────────────
            # BEAT 2: Fill form with animated typing
            # ──────────────────────────────────────────────────────────────────
            print("\n=== BEAT 2: Filling form ===")

            # Type title
            await type_into('input[name="title"]', "Weekend Data Boost 🎉", delay=0.055)
            await hold(0.6)

            # Switch to AIRTIME mode
            await set_field('select[name="reward_type"]', "AIRTIME")
            # Trigger the JS toggle
            await js("if(typeof toggleRewardFields === 'function') toggleRewardFields();")
            await hold(0.8)

            # Set network to MTN (already default)
            await set_field('select[name="network"]', "mtn")

            # Type airtime amount per slot
            await type_into('input[name="amount_per_slot"]', "200", delay=0.15)
            await hold(0.6)

            # Set number of slots
            await type_into('input[name="slots"]', "10", delay=0.18)
            await hold(1.2)   # Show the cost calc: 200 × 10 = ₦2,000 total

            # Type PIN
            await type_into('input[name="transaction_pin"]', "1234", delay=0.22)
            await hold(1.5)   # Pause — user reviewing before submitting

            # ──────────────────────────────────────────────────────────────────
            # BEAT 3: Submit → detail page (QR code + share link)
            # ──────────────────────────────────────────────────────────────────
            print("\n=== BEAT 3: Submit form ===")
            await js("document.querySelector('form').submit()")
            # Wait longer for server round trip + redirect
            await asyncio.sleep(3.5)

            detail_url = await js("window.location.href")
            print(f"[URL] After submit: {detail_url}")

            # Extract slug — URL is /giveaway/<slug>/detail/
            parts = detail_url.rstrip("/").split("/")
            slug = None
            for i, p in enumerate(parts):
                if p == "detail" and i > 0:
                    slug = parts[i - 1]
                    break
            if not slug:
                # fallback: second-to-last non-empty part
                slug = [p for p in parts if p][-2]
            print(f"[SLUG] {slug}")

            # Verify we landed on the detail page
            if "detail" not in detail_url and "giveaway" not in detail_url:
                print(f"[WARN] Unexpected URL: {detail_url}")

            # Capture detail hero (share link + QR code section)
            await hold(2.5)   # 2.5s on top of page

            # Scroll down to show QR code
            await smooth_scroll(0, 500, steps=25)
            await hold(3.0)

            # Scroll back to top → show the share link banner
            await smooth_scroll(500, 0, steps=25)
            await hold(1.5)

            # ──────────────────────────────────────────────────────────────────
            # BEAT 4: Recipient claim flow
            # ──────────────────────────────────────────────────────────────────
            print("\n=== BEAT 4: Recipient claim ===")
            claim_url = f"{BASE}/giveaway/claim/{slug}/"
            await navigate(claim_url, settle=2.5)
            await hold(2.0)

            # Type phone number
            await type_into('input[name="phone_number"]', "08145550192", delay=0.09)
            await hold(1.2)

            # Submit claim
            await js("document.querySelector('form').submit()")
            await asyncio.sleep(2.5)

            post_claim_url = await js("window.location.href")
            print(f"[URL] After claim: {post_claim_url}")

            # Hold success/pending page
            await hold(4.0)

            # ──────────────────────────────────────────────────────────────────
            # BEAT 5: Host dashboard — live tracker
            # ──────────────────────────────────────────────────────────────────
            print("\n=== BEAT 5: Host dashboard ===")
            await navigate(f"{BASE}/giveaway/{slug}/detail/", settle=2.5)
            await hold(2.0)

            # Scroll to claimant table
            await smooth_scroll(0, 600, steps=30)
            await hold(4.0)

            print(f"\n[DONE] Total frames captured: {frame_idx}")
            print(f"Frames saved to: {TARGET_DIR}")


asyncio.run(run_demo())
