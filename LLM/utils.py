import requests
import json
import time
from dotenv import load_dotenv
import os
from logger import CustomLogger
from openai import OpenAI

load_dotenv()
logger = CustomLogger(log_folder="logs/call_llm")
MAX_RETRIES = 10

def call_8b_llm(prompt: str) -> str:
    MODEL = "llama3.1:8b"
    url = os.getenv("SMALL_LLM_URL")
    payload = {
        "model": MODEL,
        "temperature": 0.7,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False
    }
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()
            logger.info(f"LLM 8B call attempt {attempt+1}: Status code {response.status_code}")
            return json.loads(response.json()["choices"][0]["message"]["content"].replace("\n", "").strip())
        except Exception as e:
            logger.warning(f"LLM 8B call attempt {attempt+1} failed: {e}")
            time.sleep(2 * attempt)
    return {}

def call_120b_llm(prompt: str) -> str:
    system_content = """
        You are a precise financial news analysis agent. Your purpose is to extract structured information from news articles with high accuracy and consistency.

        Core principles:
        - Prioritize precision over recall. If uncertain, err on the side of omission.
        - Never hallucinate, infer, or use external knowledge beyond the provided text.
        - Output strictly valid JSON only exactly as specified in the user prompt.
        - Do not add explanations, markdown, or extra commentary.
        - Follow all rules and constraints in the user prompt without deviation.

        Your outputs will be used in production financial intelligence systems where accuracy is critical. Always maintain strict adherence to the requested output format and selection criteria. and You serve a production financial intelligence system where accuracy is critical for downstream decision-making.
    """
    endpoint = "https://ai-llmmodeldeployment653596309444.services.ai.azure.com/openai/v1/"
    MODEL    = "gpt-oss-120b"
    subscription_key = os.getenv("OPENAI_API_KEY")
    client = OpenAI(
        base_url=endpoint,
        api_key=subscription_key,
    )
    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": prompt}
                ]
            )
            logger.info(f"LLM 120B call attempt {attempt+1}: Received response")
            return json.loads(response.choices[0].message.content.strip())
        except Exception as e:
            logger.warning(f"LLM 120B attempt {attempt+1} failed: {e}")
            time.sleep(2 ** attempt)
    return {}