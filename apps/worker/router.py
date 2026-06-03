from google import genai
from google.genai import types
from config import GEMINI_MODEL, GEMINI_MAX_TOKENS, GEMINI_TEMPERATURE, TOOL_TIER_MAP
from context.loader import get_profile
from tools.registry import TOOLS

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

async def route(message: str, history: list[dict], gemini_api_key: str) -> dict:
    client = genai.Client(api_key=gemini_api_key)

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

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=build_system_prompt(),
            tools=gemini_tools,
            max_output_tokens=GEMINI_MAX_TOKENS,
            temperature=GEMINI_TEMPERATURE,
        )
    )

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
                "tier": tier
            }

    text = "".join(p.text for p in candidate.parts if hasattr(p, "text") and p.text)
    return {"type": "text", "content": text}
