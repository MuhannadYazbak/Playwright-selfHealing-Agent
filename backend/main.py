import os
import sys
import asyncio
import threading
import json
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY")
)

# --- GLOBAL HELPER: PLAYWRIGHT CODE GENERATOR ---
def generate_playwright_test(test_suite_name: str, target_url: str, execution_stream: list) -> str:
    """
    Translates the autonomous execution stream into a static Playwright TypeScript test file.
    """
    safe_name = test_suite_name.replace('"', '\\"')
    
    test_code = [
        "import { test, expect } from '@playwright/test';",
        "",
        f"test('{safe_name}', async ({{ page }}) => {{",
        "  // Set default timeout for dynamic elements",
        "  test.setTimeout(60000);",
        "",
        f"  // 🌐 Navigate to target application",
        f"  await page.goto('{target_url}');",
        "  await page.waitForLoadState('domcontentloaded');",
        ""
    ]
    
    for step in execution_stream:
        if step.get("status") == "action_success":
            msg = step.get("message", "")
            timestamp = step.get("timestamp", "Action")
            
            # Match actions parsed by the engine run execution strings
            if "Executed click on:" in msg:
                selector = msg.split("Executed click on:")[1].strip()
                test_code.append(f"  // ⚡ {timestamp} - Autonomous Click Success")
                test_code.append(f"  await page.locator(\"{selector}\").click();")
                test_code.append("  await page.waitForTimeout(1000);")
                test_code.append("")
                
            elif "Executed type on:" in msg:
                selector = msg.split("Executed type on:")[1].strip()
                typed_value = step.get("typed_value", "VALUE_HERE")
                test_code.append(f"  // ⚡ {timestamp} - Autonomous Input Success")
                test_code.append(f"  await page.locator(\"{selector}\").fill('{typed_value}');")
                test_code.append("  await page.waitForTimeout(1000);")
                test_code.append("")
                
        elif step.get("status") == "completed":
            clean_msg = step.get("message", "").replace('"', '\\"')
            test_code.append("  // ✅ Objective Target Reached Verified By Agent")
            test_code.append(f"  // Reason: {clean_msg}")
    
    test_code.append("});")
    return "\n".join(test_code)


async def extract_interactive_elements(page):
    js_script = """
    () => {
        const interactiveSelectors = 'button, input, a, select, textarea, [role="button"], [contenteditable=\"true\"]';
        const elements = document.querySelectorAll(interactiveSelectors);
        const results = [];
        elements.forEach((el, index) => {
            const rect = el.getBoundingClientRect();
            const isVisible = rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).display !== 'none';
            if (isVisible) {
                results.push({
                    id: index,
                    tagName: el.tagName.toLowerCase(),
                    type: el.getAttribute('type') || null,
                    idAttribute: el.getAttribute('id') || null,
                    className: el.className || null,
                    text: el.innerText?.trim() || el.getAttribute('placeholder') || el.value || '',
                    ariaLabel: el.getAttribute('aria-label') || null
                });
            }
        });
        return results;
    }
    """
    return await page.evaluate(js_script)

async def get_next_action_from_ai(objective, elements, execution_history):
    system_prompt = """
    You are an autonomous QA automation agent navigating a web page using Playwright.
    Your goal is to fulfill the user's objective step-by-step.
    You will be provided with a JSON array representing the visible, interactive elements on the screen.
    Analyze the elements and pick the SINGLE next action required to make progress toward the objective.
    
    Allowed JSON formats for your output:
    1. {"action": "click", "elementId": 12, "reason": "Explanation"}
    2. {"action": "type", "elementId": 5, "text": "value", "reason": "Explanation"}
    3. {"action": "done", "reason": "Explanation"}
    """
    user_content = {
        "objective": objective,
        "current_page_elements": elements,
        "actions_taken_so_far": execution_history
    }
    response = client.chat.completions.create(
        model="openrouter/free",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_content)}
        ],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)


# --- THREAD WORKER INNER LOGIC ---
def run_agent_in_worker_thread(target_url, objective, main_loop, websocket):
    """Runs a dedicated Proactor loop in an isolated background thread context."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
    worker_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(worker_loop)
    
    # Storage bucket to cache stream telemetry for code conversion processing
    session_stream = []
    
    def send_to_frontend(payload):
        # Dynamically inject timestamp into payloads
        payload["timestamp"] = datetime.now().strftime("%H:%M:%S")
        session_stream.append(payload)  # Cache the log event locally
        asyncio.run_coroutine_threadsafe(websocket.send_json(payload), main_loop)

    async def core_automation_task():
        try:
            execution_history = []
            max_steps = 7

            async with async_playwright() as p:
                send_to_frontend({"status": "info", "message": "🌐 Launching isolated driver core..."})
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                send_to_frontend({"status": "info", "message": f"✈️ Navigating to {target_url}..."})
                await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                
                try:
                    await page.wait_for_selector("body", state="visible", timeout=10000)
                    await asyncio.sleep(2)
                except Exception:
                    send_to_frontend({"status": "info", "message": "⚠️ Main layout container loading timed out. Proceeding anyway..."})
                
                for step in range(1, max_steps + 1):
                    send_to_frontend({"status": "step_start", "step": step})
                    elements = await extract_interactive_elements(page)
                    
                    send_to_frontend({"status": "thinking", "message": "🤖 AI is computing next action..."})
                    ai_decision = await get_next_action_from_ai(objective, elements, execution_history)
                    
                    send_to_frontend({"status": "decision", "data": ai_decision})
                    
                    action = ai_decision.get("action")
                    reason = ai_decision.get("reason")
                    
                    if action == "done":
                        send_to_frontend({"status": "completed", "message": f"✅ Objective Achieved: {reason}"})
                        break
                        
                    element_id = ai_decision.get("elementId")
                    target_el_data = next((el for el in elements if el["id"] == element_id), None)
                    
                    if not target_el_data:
                        send_to_frontend({"status": "error", "message": f"AI selected invalid ID {element_id}"})
                        continue
                    
                    # --- HARDENED MULTI-TIERED SELECTOR GENERATOR ---
                    selectors_to_try = []
                    if target_el_data.get("idAttribute"):
                        selectors_to_try.append(f"#{target_el_data['idAttribute']}")
                    if target_el_data.get("text"):
                        clean_text = target_el_data["text"].replace("'", "\\'")
                        selectors_to_try.append(f"{target_el_data['tagName']}:has-text('{clean_text}')")
                        if target_el_data["tagName"] == "input":
                            selectors_to_try.append(f"input[placeholder='{clean_text}']")
                    if target_el_data.get("type"):
                        selectors_to_try.append(f"{target_el_data['tagName']}[type='{target_el_data['type']}']")
                    selectors_to_try.append(f"css={target_el_data['tagName']} >> nth={elements.index(target_el_data)}")

                    selectors_to_try = list(dict.fromkeys(selectors_to_try))
                    
                    # --- SELF-HEALING EXECUTION ENGINE ---
                    action_success = False
                    last_execution_error = ""
                    
                    for attempt_idx, selector in enumerate(selectors_to_try):
                        try:
                            if action == "click":
                                await page.click(selector, timeout=3000)
                                execution_history.append(f"Clicked via selector: {selector}")
                                send_to_frontend({
                                    "status": "action_success", 
                                    "message": f"⚡ [Strategy {attempt_idx + 1}] Executed click on: {selector}"
                                })
                            elif action == "type":
                                input_text = ai_decision.get("text", "")
                                await page.fill(selector, input_text, timeout=3000)
                                execution_history.append(f"Typed into selector: {selector}")
                                send_to_frontend({
                                    "status": "action_success", 
                                    "message": f"⚡ [Strategy {attempt_idx + 1}] Executed type on: {selector}",
                                    "typed_value": input_text
                                })
                            
                            action_success = True
                            await asyncio.sleep(1.5)
                            break 
                            
                        except Exception as e:
                            last_execution_error = str(e)
                            send_to_frontend({
                                "status": "info", 
                                "message": f"⚠️ Strategy {attempt_idx + 1} failed ({selector}). Attempting fallback..."
                            })
                    
                    if not action_success:
                        error_msg = f"❌ All self-healing selectors exhausted. Final error: {last_execution_error}"
                        send_to_frontend({"status": "action_failed", "message": error_msg})
                        execution_history.append(f"TOTAL FRAMEWORK FAILURE on element {element_id}")

                # 🔥 EXECUTE COMPILATION TASK BEFORE DEALLOCATING CORE DRIVER 🔥
                send_to_frontend({"status": "info", "message": "📦 Compiling execution history into static Playwright script..."})
                generated_spec = generate_playwright_test(
                    test_suite_name=f"Autonomous Run - {objective}",
                    target_url=target_url,
                    execution_stream=session_stream
                )
                
                # Forward spec bundle message down to web socket channel
                send_to_frontend({
                    "status": "code_export_ready",
                    "playwright_code": generated_spec
                })

                await browser.close()
        except Exception as e:
            send_to_frontend({"status": "error", "message": f"Critical engine crash: {str(e)}"})

    worker_loop.run_until_complete(core_automation_task())
    worker_loop.close()


@app.websocket("/ws/run-agent")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("🔌 Frontend connected to agent stream websocket.")
    main_loop = asyncio.get_running_loop()
    
    try:
        data = await websocket.receive_text()
        config = json.loads(data)
        target_url = config.get("url")
        objective = config.get("objective")
        
        threading.Thread(
            target=run_agent_in_worker_thread,
            args=(target_url, objective, main_loop, websocket),
            daemon=True
        ).start()
        
        while True:
            await asyncio.sleep(1)
            
    except WebSocketDisconnect:
        print("❌ Frontend disconnected prematurely.")
    finally:
        print("🏁 Connection lifecycle finalized.")