from dotenv import load_dotenv
import os, requests, time, json
from logger import CustomLogger
from .utils import call_8b_llm, call_120b_llm
load_dotenv()
logger = CustomLogger(log_folder="logs/small_llm")

MODEL = "llama3.1:8b"
BATCH_SIZE = 50
MAX_RETRIES = 10

class CallLLM:
    def __init__(self, small_llm: bool = True):
        self.small_llm = small_llm
        self.url = os.getenv("SMALL_LLM_URL")

    def call_llm(self,prompt: str) -> str:
        if self.small_llm:
            return call_8b_llm(prompt)
        else:
            return call_120b_llm(prompt)
    
    def get_description(self, company_text: str) -> dict:
        truncated = company_text.strip()[:5000]
        prompt = f"""You are a professional business writer and copywriter.

            Using ONLY the information provided below, write a compelling company description of approximately 250 words.

            Requirements:
            - Write in third-person, professional yet engaging tone.
            - Cover what the company does, its core products/services, mission, and value proposition.
            - Sound like a human copywriter wrote it -- natural, confident, not robotic.
            - Do NOT use filler phrases like "In conclusion", "The company strives", or "leverages cutting-edge".
            - Do NOT add any information that is not in the source text.
            - Output ONLY valid JSON in this exact format -- no markdown, no explanation, nothing else:
            {{"description": "<your 250-word description here>"}}

            Source information:
            {truncated}
        """
        try:
            response = self.call_llm(prompt)
            if not response:
                return ""
            description = response.get("description", "").strip()
            if not isinstance(description, str):
                return ""
            return description
        except Exception as e:
            logger.error(f"Error parsing get_description LLM response: {e}")
            return ""

    def test_import(self):
        logger.info("SmallLLM import successful!")
        return "SmallLLM import successful!"