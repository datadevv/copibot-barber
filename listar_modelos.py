import os
from google import genai

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
for m in client.models.list():
    if "flash-lite" in m.name or "3.8-flash" in m.name:
        print(m.name)