import asyncio
import json
from datetime import datetime
from google import genai
from google.genai import types
from google.genai.errors import APIError
from config import GEMINI_MODEL, GEMINI_LITE_MODEL, GEMINI_MAX_TOKENS, GEMINI_TEMPERATURE, TOOL_TIER_MAP, OLLAMA_HOST, OLLAMA_MODEL
from context.loader import get_profile
from tools.registry import TOOLS
from supabase import Client
from budget_gate import pick_model, check_and_increment

def build_system_prompt() -> str:
    profile = get_profile()
    base = (
        "You are Project Sunday, a personal AI assistant running on Alstone's Mac.\n"
        "You help with tasks by calling tools. Always use the minimum necessary tool.\n"
        "For each tool call, the tier is enforced by the worker — you cannot change it.\n"
        "Respond concisely. If no tool is needed, reply directly.\n"
        "\n"
        "TASK EXTRACTION:\n"
        "When the user mentions something they need to do, a reminder, a deadline,\n"
        "or a to-do item in conversation, proactively call task_create to capture it.\n"
        "Examples: 'I need to buy groceries', 'remind me to call the dentist',\n"
        "'that report is due Friday'. Set appropriate priority and due_date.\n"
        "Don't create tasks for things that are already done or purely conversational.\n"
        "\n"
        "CALENDAR:\n"
        "You can query, create, and update Google Calendar events.\n"
        "When creating events, always confirm the time with the user first.\n"
        "Use Australia/Sydney timezone for all events.\n"
        "\n"
        "EMAILS:\n"
        "You can search Gmail, read individual email bodies, and scan for priority emails.\n"
        "You can also create drafts. Never send emails directly — always draft first.\n"
    )
    if profile:
        base += f"\n\n--- USER PROFILE ---\n{profile}\n--- END PROFILE ---\n"
    return base

async def _ask_ollama(message: str, history: list[dict]) -> dict:
    from ollama import AsyncClient
    
    messages = [{"role": "system", "content": build_system_prompt()}]
    for h in history[-20:]:
        role = "user" if h["role"] == "user" else "assistant"
        messages.append({"role": role, "content": h["content"]})
    messages.append({"role": "user", "content": message})
    
    try:
        client = AsyncClient(host=OLLAMA_HOST)
        response = await client.chat(
            model=OLLAMA_MODEL,
            messages=messages
        )
        reply = response.message.content or "No response from Ollama."
        return {"type": "text", "content": f"[Ollama] {reply}", "model_used": "ollama"}
    except Exception as e:
        return {"type": "text", "content": f"Ollama failed to respond: {e}", "model_used": "system"}

# record_llm_usage removed — all recording is now via budget_gate.check_and_increment

async def route(client: Client, message: str, history: list[dict], gemini_api_key: str, user_id: str) -> dict:
    if message.strip().startswith("/private"):
        clean_msg = message.replace("/private", "", 1).strip()
        print(f"[router] explicit private routing triggered")
        return await _ask_ollama(clean_msg, history)

    # 1. Brain-dump detection
    msg_lower = message.lower()
    is_brain_dump = False
    if "add these tasks" in msg_lower or "brain dump" in msg_lower or "braindump" in msg_lower:
        is_brain_dump = True
    elif message.count("- ") + message.count("* ") + message.count("• ") >= 3:
        is_brain_dump = True
    elif "1." in message and "2." in message and "3." in message:
        is_brain_dump = True
    elif message.count(",") >= 4 and len(message.split()) < 50 and ("need to" in msg_lower or "have to" in msg_lower):
        is_brain_dump = True

    if is_brain_dump:
        print("[router] brain-dump detected, using structured extraction...")
        ai_client = genai.Client(api_key=gemini_api_key)
        
        schema = {
            "type": "OBJECT",
            "properties": {
                "tasks": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "title": {"type": "STRING", "description": "The task description"},
                            "tags": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Inferred tags e.g. Personal, Career"},
                            "flexibility_score": {"type": "INTEGER", "description": "1 to 5 (1=strict, 5=highly flexible)"}
                        },
                        "required": ["title", "tags", "flexibility_score"]
                    }
                }
            },
            "required": ["tasks"]
        }
        
        try:
            model_id = await pick_model(client, user_id)
            if model_id == "EXHAUSTED":
                return {"type": "text", "content": "You've hit today's free-tier LLM limit. Please try again later.", "model_used": "system"}
            if model_id == "ollama":
                return {"type": "text", "content": "Budget exhausted — brain-dump parsing requires a cloud model. Please try again tomorrow.", "model_used": "system"}
            response = await asyncio.to_thread(
                lambda: ai_client.models.generate_content(
                    model=model_id,
                    contents=[
                        types.Content(role="user", parts=[types.Part(text=message)])
                    ],
                    config=types.GenerateContentConfig(
                        system_instruction="Extract tasks from the user's brain-dump into a structured JSON list.",
                        response_mime_type="application/json",
                        response_schema=schema,
                        temperature=0.1
                    )
                )
            )
            await check_and_increment(client, user_id, model_id)
            
            raw_json = response.candidates[0].content.parts[0].text
            data = json.loads(raw_json)
            tasks = data.get("tasks", [])
            
            if tasks:
                inserted = 0
                for t in tasks:
                    await asyncio.to_thread(
                        lambda: client.table("tasks").insert({
                            "user_id": user_id,
                            "title": t["title"],
                            "tags": t["tags"],
                            "flexibility_score": t["flexibility_score"],
                            "category": "personal",
                            "source": "chat"
                        }).execute()
                    )
                    inserted += 1
                
                reply = f"I created {inserted} tasks from your brain-dump. Here is what I categorized:\n"
                for t in tasks:
                    tags_str = ", ".join(t.get("tags", []))
                    reply += f"- **{t['title']}** (Tags: {tags_str}, Flex: {t.get('flexibility_score', 3)})\n"
                
                return {"type": "text", "content": reply, "model_used": model_id}
            else:
                return {"type": "text", "content": "I couldn't detect any tasks in your brain-dump.", "model_used": model_id}
                
        except Exception as e:
            return {"type": "text", "content": f"Failed to parse brain-dump: {e}", "model_used": "system"}

    client_genai = genai.Client(api_key=gemini_api_key)

    gemini_tools = [
        types.Tool(function_declarations=[
            types.FunctionDeclaration(
                name=t["name"],
                description=t["description"],
                parameters=t["parameters"]
            ) for t in TOOLS
        ])
    ]

    contents = []
    for h in history[-20:]:
        role = "user" if h["role"] == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part(text=h["content"])]))
    contents.append(types.Content(role="user", parts=[types.Part(text=message)]))

    # Budget-aware model selection: pick the best available tier (defaults to allow_flash=True)
    budget_model = await pick_model(client, user_id)
    if budget_model == "EXHAUSTED":
        print("[router] All LLMs exhausted for user.")
        return {"type": "text", "content": "You've hit today's free-tier LLM limit. Please try again later.", "model_used": "system"}
    if budget_model == "ollama":
        print("[router] All Gemini tiers exhausted for user. Falling back to Ollama.")
        return await _ask_ollama(message, history)

    # Build cascade: start from the budget-allowed tier downward
    if budget_model == GEMINI_MODEL:
        models_to_try = [GEMINI_MODEL, GEMINI_LITE_MODEL]
    else:
        models_to_try = [GEMINI_LITE_MODEL]

    for model_id in models_to_try:
        try:
            print(f"[router] Attempting generation with {model_id}...")
            response = await asyncio.to_thread(
                lambda: client_genai.models.generate_content(
                    model=model_id,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=build_system_prompt(),
                        tools=gemini_tools,
                        max_output_tokens=GEMINI_MAX_TOKENS,
                        temperature=GEMINI_TEMPERATURE,
                    )
                )
            )
            await check_and_increment(client, user_id, model_id)

            candidate = response.candidates[0].content
            for part in candidate.parts:
                if part.function_call:
                    fn = part.function_call
                    tool_name = fn.name
                    tier = TOOL_TIER_MAP.get(tool_name, "approve")
                    return {
                        "type": "tool_call",
                        "tool": tool_name,
                        "args": dict(fn.args),
                        "tier": tier,
                        "model_used": model_id
                    }

            text = "".join(p.text for p in candidate.parts if hasattr(p, "text") and p.text)
            return {"type": "text", "content": text, "model_used": model_id}

        except APIError as e:
            if e.code in [429, 503]:
                print(f"[router] {model_id} exhausted or unavailable (Error {e.code}). Cascading to next model...")
                continue
            else:
                return {"type": "text", "content": f"Google API Error: {e.message}", "model_used": "system"}
        except Exception as e:
            return {"type": "text", "content": f"Unexpected Error: {e}", "model_used": "system"}

    print("[router] Google models exhausted. Failing over to local Ollama...")
    return await _ask_ollama(message, history)
