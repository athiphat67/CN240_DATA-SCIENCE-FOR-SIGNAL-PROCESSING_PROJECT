import os
from agent_core.core.prompt import PromptPackage
from agent_core.llm.client import LLMClientFactory

# 1. ตั้งค่า API Key (หรือตั้งในไฟล์ .env)
os.environ["OPENROUTER_API_KEY"] = "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"

# 2. สร้าง Prompt Package (สมมติตามโครงสร้างของคุณ)
prompt = PromptPackage(
    system="You are a helpful assistant.",
    user="What is the capital of Japan?",
    step_label="TEST_OPENROUTER"
)

# 3. เรียกใช้ Factory โดยระบุ provider="openrouter" และชื่อ model ที่ต้องการ
client = LLMClientFactory.create(
    provider="openrouter", 
    model="anthropic/claude-3-haiku" # ตัวอย่างการเรียกใช้ Claude 3 ผ่าน OpenRouter
)

# 4. ส่ง Request
response = client.call(prompt)
print(response.text)