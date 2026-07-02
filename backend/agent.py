import asyncio
import json
import os
from playwright.async_api import async_playwright
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
# Initialize OpenAI Client (automatically reads OPENAI_API_KEY from environment)
# Initialize OpenAI Client directly with your key
# Initialize OpenAI Client pointing to OpenRouter's free endpoint
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY")  # Paste your free OpenRouter key here
)

async def extract_interactive_elements(page):
    js_script = """
    () => {
        const interactiveSelectors = 'button, input, a, select, textarea, [role="button"], [contenteditable="true"]';
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
    """
    Sends the current DOM state, overall objective, and history to OpenAI
    to decide the next action step in structured JSON format.
    """
    system_prompt = """
    You are an autonomous QA automation agent navigating a web page using Playwright.
    Your goal is to fulfill the user's objective step-by-step.
    
    You will be provided with a JSON array representing the visible, interactive elements on the screen.
    Analyze the elements and pick the SINGLE next action required to make progress toward the objective.
    
    Allowed JSON formats for your output:
    1. To click an element:
       {"action": "click", "elementId": 12, "reason": "Brief explanation"}
    2. To input text into a field:
       {"action": "type", "elementId": 5, "text": "your-input-value", "reason": "Brief explanation"}
    3. If the objective has been completely satisfied:
       {"action": "done", "reason": "Successfully logged in / verified result"}

    CRITICAL RULES:
    - Respond ONLY with a valid, raw JSON object. Do not wrap it in markdown code blocks.
    - Only reference 'id' values that explicitly exist in the provided interactive elements array.
    """

    user_content = {
        "objective": objective,
        "current_page_elements": elements,
        "actions_taken_so_far": execution_history
    }

    response = client.chat.completions.create(
        model="gpt-4o-mini",  # Fast and highly performant for structured automation tasks
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_content)}
        ],
        response_format={"type": "json_object"}  # Forces valid JSON output
    )

    return json.loads(response.choices[0].message.content)

async def main():
    objective = "Log into the application using username 'tomsmith' and password 'SuperSecretPassword!'"
    execution_history = []
    max_steps = 5  # Guardrail to prevent infinite loops

    async with async_playwright() as p:
        print("🌐 Launching browser...")
        browser = await p.chromium.launch(headless=False)  # Set to False so you can watch it happen!
        page = await browser.new_page()
        
        target_url = "https://the-internet.herokuapp.com/login"
        print(f"✈️ Navigating to: {target_url}")
        await page.goto(target_url)
        
        # 🧪 BREAK THE DOM ON PURPOSE TO TEST SELF-HEALING
        print("🔧 Intentionally altering the DOM to test self-healing...")
        await page.evaluate("""() => {
            const usernameInput = document.getElementById('username');
            if (usernameInput) {
                // Completely strip the predictable ID 'username'
                usernameInput.removeAttribute('id');
                // Change its class name to something entirely random
                usernameInput.className = 'broken-input-field-xyz';
                // Add an arbitrary data tag
                usernameInput.setAttribute('data-legacy-field', 'user-entry');
            }
        }""")
        
        for step in range(1, max_steps + 1):
            print(f"\n🎬 --- Step {step} ---")
            
            # 1. Scan the page
            elements = await extract_interactive_elements(page)
            
            # 2. Query the AI for the decision
            print("🤖 Thinking about the next action...")
            ai_decision = await get_next_action_from_ai(objective, elements, execution_history)
            print(f"💡 AI Decision: {json.dumps(ai_decision, indent=2)}")
            
            action = ai_decision.get("action")
            reason = ai_decision.get("reason")
            
            if action == "done":
                print(f"✅ Success! Objective complete: {reason}")
                break
                
            element_id = ai_decision.get("elementId")
            
            # Find the matching element in our Python data stream to retrieve attributes
            target_el_data = next((el for el in elements if el["id"] == element_id), None)
            if not target_el_data:
                print(f"❌ Error: AI suggested a non-existent element ID {element_id}. Retrying workflow...")
                continue
            
            # Reconstruct a dynamic selector based on what data attributes we collected
            # Fallback to the text strategy or index mapping if ID/Class attributes aren't present
            # --- FIX: ROBUST SELECTOR STRATEGY ---
            if target_el_data["idAttribute"]:
                selector = f"#{target_el_data['idAttribute']}"
            elif target_el_data["tagName"] == "button" and target_el_data["text"]:
                selector = f"button:has-text('{target_el_data['text']}')"
            elif target_el_data["type"] == "text":
                # Fallback specifically for broken text inputs
                selector = "input[type='text']"
            else:
                # Use a perfectly valid Playwright CSS index selector instead of the broken syntax
                selector = f"css={target_el_data['tagName']} >> nth={elements.index(target_el_data)}"
            # -------------------------------------

            # 3. Execute the Playwright Action Dynamically
            print(f"⚡ Executing dynamic action '{action}' on selector '{selector}'")
            try:
                if action == "click":
                    await page.click(selector)
                    execution_history.append(f"Clicked element with selector: {selector} because: {reason}")
                elif action == "type":
                    input_text = ai_decision.get("text", "")
                    await page.fill(selector, input_text)
                    execution_history.append(f"Typed text into selector: {selector} because: {reason}")
                
                # Small wait to let the page adjust / animations load
                await asyncio.sleep(1.5)
                
            except Exception as e:
                print(f"⚠️ Action failed! Error: {str(e)}")
                execution_history.append(f"FAILED to execute {action} on {selector}. Error: {str(e)}")

        print("\n🏁 Automation run complete.")
        await asyncio.sleep(3)  # Let you look at the final state before closing
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())