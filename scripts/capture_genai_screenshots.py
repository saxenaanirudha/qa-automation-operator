"""
Automated Authentic Screenshot Capture for Generative AI Features.

Uses headless Chrome via Chrome DevTools Protocol (CDP) to capture exact 1920x1080 (16:9)
screenshots of authentic generated dashboards into reports/screenshots/genai/.
"""

import asyncio
import json
import os
import subprocess
import time
import urllib.request
import base64
import websockets

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
TEMP_PROFILE = os.path.join(os.environ["TEMP"], f"chrome_genai_cdp_{int(time.time())}")
PORT = 9223
SCREENSHOTS_DIR = r"C:\Users\Anirudha\Downloads\Antigravity-Projects\qa-automation-operator\reports\screenshots\genai"
WORKSPACE_DIR = r"C:\Users\Anirudha\Downloads\Antigravity-Projects\qa-automation-operator"

async def send_cmd(ws, method, params=None, id_counter=[1]):
    cid = id_counter[0]
    id_counter[0] += 1
    req = {"id": cid, "method": method, "params": params or {}}
    await ws.send(json.dumps(req))
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("id") == cid:
            return msg.get("result", {})

async def capture_page(ws, url, out_name, wait_sec=2, scroll_y=0, wait_selector=None):
    print(f"\n--- Capturing: {out_name} ---")
    print(f"Navigating to {url}...")
    await send_cmd(ws, "Page.enable")
    await send_cmd(ws, "DOM.enable")
    await send_cmd(ws, "Emulation.setDeviceMetricsOverride", {
        "width": 1920,
        "height": 1080,
        "deviceScaleFactor": 1,
        "mobile": False
    })
    await send_cmd(ws, "Page.navigate", {"url": url})
    await asyncio.sleep(wait_sec)

    if wait_selector:
        print(f"Waiting for selector: {wait_selector}...")
        for attempt in range(25):
            eval_res = await send_cmd(ws, "Runtime.evaluate", {
                "expression": f"document.querySelector('{wait_selector}') !== null"
            })
            if eval_res.get("result", {}).get("value") is True:
                print(f"Selector found after {attempt * 0.5:.1f}s")
                break
            await asyncio.sleep(0.5)
        await asyncio.sleep(1.5)

    if scroll_y > 0:
        print(f"Scrolling to Y={scroll_y}...")
        await send_cmd(ws, "Runtime.evaluate", {
            "expression": f"window.scrollTo(0, {scroll_y});"
        })
        await asyncio.sleep(1.0)

    res = await send_cmd(ws, "Page.captureScreenshot", {"format": "png"})
    png_bytes = base64.b64decode(res["data"])
    out_path = os.path.join(SCREENSHOTS_DIR, out_name)
    with open(out_path, "wb") as f:
        f.write(png_bytes)
    print(f"Saved: {out_path} ({len(png_bytes)} bytes)")
    return out_path

async def main():
    os.makedirs(TEMP_PROFILE, exist_ok=True)
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

    cmd = [
        CHROME_PATH,
        f"--remote-debugging-port={PORT}",
        f"--user-data-dir={TEMP_PROFILE}",
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1920,1080",
        "about:blank"
    ]
    print("Launching Chrome headless process...")
    proc = subprocess.Popen(cmd)

    try:
        page_ws_url = None
        for _ in range(25):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=1) as resp:
                    tabs = json.loads(resp.read().decode())
                    for tab in tabs:
                        if tab.get("type") == "page" and "webSocketDebuggerUrl" in tab:
                            page_ws_url = tab["webSocketDebuggerUrl"]
                            break
                    if page_ws_url:
                        break
            except Exception:
                time.sleep(0.5)

        if not page_ws_url:
            raise RuntimeError("Could not find open page WebSocket in Chrome.")

        print(f"Connected to Page CDP: {page_ws_url}")

        async with websockets.connect(page_ws_url, max_size=50*1024*1024) as ws:
            # Screenshot 1: AI Test Summary on Successful Build
            report_a_url = "file:///" + os.path.join(WORKSPACE_DIR, "reports", "qa_report_ai_success.html").replace("\\", "/")
            await capture_page(
                ws,
                report_a_url,
                "screenshot_1_ai_summary.png",
                wait_sec=2,
                scroll_y=350,
                wait_selector=".ai-insights-section"
            )

            # Screenshot 2: AI Probable Root Cause Analysis on Synthetic Failed Build
            report_b_url = "file:///" + os.path.join(WORKSPACE_DIR, "reports", "qa_report_ai_failure.html").replace("\\", "/")
            await capture_page(
                ws,
                report_b_url,
                "screenshot_2_ai_root_causes.png",
                wait_sec=2,
                scroll_y=350,
                wait_selector=".ai-insights-section"
            )

            # Screenshot 3: AI Recommended Test Scenarios
            await capture_page(
                ws,
                report_b_url,
                "screenshot_3_ai_recommended_scenarios.png",
                wait_sec=1,
                scroll_y=600,
                wait_selector=".ai-recommendations-list"
            )

        print("\nAll dashboard screenshots captured successfully in reports/screenshots/genai/!")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()

if __name__ == "__main__":
    asyncio.run(main())
