# test_client.py
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.abspath(os.path.join(current_dir, "../../"))

if src_path not in sys.path:
    sys.path.insert(0, src_path)
    
from agent_core.core.prompt import PromptPackage
from client import LLMClientFactory

# --- Prompt ทดสอบ ---
TEST_PROMPT = PromptPackage(
    system="You are a helpful assistant. Reply in JSON only.",
    user='Say hello and return {"status": "ok", "message": "hello"}',
    step_label="TEST",
)

def test_provider(name: str, **kwargs):
    print(f"\n{'='*40}")
    print(f"Testing: {name.upper()}")
    print(f"{'='*40}")
    try:
        client = LLMClientFactory.create(name, **kwargs)
        print(f"  init    : OK  ({client})")

        available = client.is_available()
        print(f"  available: {available}")

        response = client.call(TEST_PROMPT)
        print(f"  response: {response[:120]}")
        print(f"  PASS")
    except Exception as e:
        print(f"  FAIL -> {type(e).__name__}: {e}")


if __name__ == "__main__":

    # 1. Mock  
    test_provider("mock")

    # 2. Gemini 
    test_provider("gemini")

    # 3. OpenAI - เสียตัง
    #test_provider("openai")

    # 4. Claude - เสียตัง
    #test_provider("claude")
    
    # 5. Groq
    #test_provider("groq")
    
    # 6. Deepseek - เสียตัง
    #test_provider("deepseek")
    
    #test_provider("ollama")