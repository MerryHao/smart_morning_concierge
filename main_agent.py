"""
main_agent.py — Smart Morning Concierge (智慧早晨出門管家)
Agent ADK implementation using Google Gemini with a bound weather tool.

Architecture:
  ┌─────────────────────────────────────────────────┐
  │  CLI (terminal loop)                            │
  │        │  user input (location)                 │
  │        ▼                                        │
  │  Gemini Agent (gemini-2.5-flash)                │
  │    • system_instruction: concierge persona      │
  │    • tools: [get_weather]  ◄── MCP Tool layer   │
  │        │  auto function call                    │
  │        ▼                                        │
  │  weather_tool.get_weather(location_name)        │
  │    • calls CWA Open Data API                    │
  │        │  structured weather string             │
  │        ▼                                        │
  │  Gemini generates friendly advice response      │
  └─────────────────────────────────────────────────┘
"""

import os
import sys
import time
from dotenv import load_dotenv
import google.genai as genai
from google.genai import types

# Import our MCP tool
from weather_tool import get_weather

# ── Bootstrap ───────────────────────────────────────────────────────────────

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("❌ 錯誤：找不到 GEMINI_API_KEY，請確認 .env 檔案已正確設定。")
    sys.exit(1)

MODEL_ID = "gemini-2.5-flash"  # 換新 API Key 後使用此模型（品質最佳）

# ── System Instruction ───────────────────────────────────────────────────────

SYSTEM_INSTRUCTION = """
You are a Smart Concierge AI assistant that helps users decide what to wear and whether to bring an umbrella based on the current weather in Taiwan.

Your task flow (strictly follow this):
1. The user provides a Taiwan city or county name.
2. You MUST call the get_weather tool to retrieve real weather data. Do not skip this step.
3. Based on the weather data, respond in a warm, friendly tone like a helpful friend, providing:
   a. Outfit suggestion: based on temperature and weather condition, recommend what to wear (e.g. light jacket, raincoat, t-shirt).
   b. Umbrella reminder: based on precipitation probability, advise whether to bring an umbrella or rain gear.
   c. A short encouraging closing note.

Style requirements:
- Write naturally and conversationally, like a text from a friend.
- Use emojis sparingly to add warmth.
- Keep it concise and clear.
- Always respond in English.
""".strip()

# ── Gemini Client & Tool Setup ───────────────────────────────────────────────

client = genai.Client(api_key=GEMINI_API_KEY)

# Bind get_weather as a callable tool for the Gemini agent
weather_tool = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="get_weather",
        description=(
            "查詢台灣指定縣市的天氣預報資訊，包含天氣現象、降雨機率、最低溫與最高溫。"
            "使用者提供縣市名稱（繁體中文，例如：桃園市、台北市），即可取得最近 12 小時的天氣概況。"
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "location_name": types.Schema(
                    type=types.Type.STRING,
                    description="台灣縣市名稱，使用繁體中文，例如：桃園市、台北市、高雄市。",
                )
            },
            required=["location_name"],
        ),
    )
])

# ── Agent Loop (Agentic Tool-Use) ────────────────────────────────────────────

def _generate_with_retry(model: str, contents, config, max_retries: int = 3):
    """
    Call client.models.generate_content with exponential backoff on 429/503 errors.
    Only retries per-minute rate limits (retryDelay ≤ 45s).
    Daily quota exhaustion (retryDelay > 45s) fails fast with a clear message.
    """
    delay = 15  # seconds — starts above the typical per-minute retry window
    for attempt in range(max_retries):
        try:
            return client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
        except Exception as e:
            err_str = str(e)
            is_rate_limited = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
            is_unavailable  = "503" in err_str or "UNAVAILABLE" in err_str

            if is_rate_limited:
                # Parse retryDelay to distinguish daily vs per-minute quota
                import re
                match = re.search(r"retryDelay.*?(\d+)s", err_str)
                retry_delay_sec = int(match.group(1)) if match else 0
                if retry_delay_sec > 45:
                    # Daily quota exhausted — retrying won't help today
                    raise RuntimeError(
                        "今日 Gemini API 免費配額已用完 😓\n"
                        "請明天再試，或前往 https://aistudio.google.com 啟用付費方案。\n"
                        f"（原始錯誤：{retry_delay_sec}s retry delay）"
                    ) from e

            if (is_rate_limited or is_unavailable) and attempt < max_retries - 1:
                print(f"[retry] Gemini rate-limited, waiting {delay}s (attempt {attempt+1}/{max_retries})...")
                time.sleep(delay)
                delay *= 2  # exponential backoff: 15s → 30s → 60s
            else:
                raise


def run_agent(user_message: str) -> str:
    """
    Run one turn of the concierge agent with automatic tool execution.

    The function implements a simple agentic loop:
      1. Send user message to Gemini.
      2. If Gemini requests a tool call, execute it locally and feed the result back.
      3. Repeat until Gemini returns a final text response.

    Args:
        user_message: The location entered by the user.

    Returns:
        The agent's final text response as a string.
    """
    contents: list[types.Content] = [
        types.Content(
            role="user",
            parts=[types.Part(text=user_message)],
        )
    ]

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        tools=[weather_tool],
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode=types.FunctionCallingConfigMode.AUTO,
            )
        ),
        temperature=0.7,
    )

    # Agentic loop — handles multi-turn tool calls automatically
    max_iterations = 5
    for _ in range(max_iterations):
        response = _generate_with_retry(
            model=MODEL_ID,
            contents=contents,
            config=config,
        )

        # Guard: no candidates returned
        if not response.candidates:
            return "⚠️ AI 管家暫時無法回應，請稍後再試。"

        candidate = response.candidates[0]
        finish_reason = str(candidate.finish_reason)

        # Guard: safety filter or empty content
        content = candidate.content
        if content is None or not content.parts:
            if "SAFETY" in finish_reason:
                return "⚠️ 回應因安全過濾器被攔截，請換個方式詢問。"
            return "⚠️ AI 管家暫時無法回應，請稍後再試。"

        parts = content.parts

        # Check if there are any function calls in the response
        function_call_parts = [p for p in parts if p.function_call is not None]
        text_parts = [p for p in parts if p.text is not None]

        # If no function calls, we have the final text answer
        if not function_call_parts:
            result = "\n".join(p.text for p in text_parts if p.text).strip()
            if not result:
                return "⚠️ AI 管家暫時無法回應，請稍後再試。"
            return result

        # Execute each function call and collect results
        function_response_parts = []
        for part in function_call_parts:
            fc = part.function_call
            if fc.name == "get_weather":
                location = fc.args.get("location_name", "")
                tool_result = get_weather(location)
                function_response_parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name="get_weather",
                            response={"result": tool_result},
                        )
                    )
                )

        # Append the model's tool-call turn and the tool results to the conversation
        contents.append(types.Content(role="model", parts=parts))
        contents.append(
            types.Content(role="user", parts=function_response_parts)
        )
        # Loop again to get the final text response

    return "⚠️ AI 管家處理時間過長，請稍後再試。"

# ── CLI Entry Point ───────────────────────────────────────────────────────────

BANNER = """
╔══════════════════════════════════════════════════════════╗
║       🌅  智慧早晨出門管家  Smart Morning Concierge       ║
║              Powered by Google Gemini 2.5 Flash           ║
╚══════════════════════════════════════════════════════════╝
  輸入台灣縣市名稱取得出門建議，輸入 "exit" 離開。
  Enter a Taiwan city/county name for morning advice.
"""

def main():
    """Main CLI loop for the Smart Morning Concierge."""
    print(BANNER)

    while True:
        try:
            user_input = input("📍 請輸入縣市（例如：桃園市）> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n👋 掰掰！祝你今天一切順利！")
            break

        if not user_input:
            print("⚠️  請輸入一個縣市名稱，例如：台北市、桃園市、高雄市。\n")
            continue

        if user_input.lower() in ("exit", "quit", "bye", "掰掰", "再見"):
            print("\n👋 掰掰！祝你今天一切順利！")
            break

        print(f"\n⏳ 正在查詢「{user_input}」的天氣並準備建議，請稍候...\n")

        try:
            reply = run_agent(user_input)
            print("─" * 55)
            print(reply)
            print("─" * 55 + "\n")
        except Exception as e:
            print(f"❌ 發生錯誤：{e}\n請檢查您的 GEMINI_API_KEY 是否有效，或稍後再試。\n")


if __name__ == "__main__":
    main()
