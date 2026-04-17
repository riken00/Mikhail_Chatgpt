import json
import logging
import re
import time
from typing import Optional, Dict, List, Any

from openai import OpenAI
from .bot import Bot

logger = logging.getLogger("llm_service")

# Standard sector list across the application
SECTORS_LIST = [
    "Agriculture", "Construction Tech", "Enterprise Software", "F&B",
    "Finance", "Hospitality", "Real Estate Tech", "Metaverse", "Mining",
    "Nanotechnology", "Quantum Computing", "Retail", "Space Tech",
    "Sports", "Sustainability Tech", "Telecom", "Transportation",
    "Virtual Reality", "Robotics", "Legal", "AI Infrastructure",
    "Augmented Reality", "Beauty Tech", "Blockchain Infrastructure",
    "Chemicals and Materials Tech", "Cyber Security", "Drone Tech",
    "Education", "Energy", "Enterprise Infrastructure", "Fashion Tech",
    "GenerativeAI", "Geographic Information Systems", "Healthcare",
    "HR Tech", "IOT", "Manufacturing", "Marketing & Ad Tech",
    "Advanced Materials"
]

# Standard channels map
CHANNELS_MAP = {
    "ch-funding":      "Funding & Raises",
    "ch-partnerships": "Partnerships & Alliances",
    "ch-ma":           "M&A Activity",
    "ch-investments":  "Strategic Investments",
    "ch-gov-policy":   "Government & Policy",
    "ch-company-news": "Company News & Product Launches",
    "ch-regulatory":   "Regulatory Milestones",
}

class LLMService:
    """
    Unified LLM service supporting both OpenAI API and Selenium-based ChatGPT.
    """

    def __init__(self, engine: str = "selenium", **kwargs):
        """
        :param engine: 'openai' or 'selenium'
        :param kwargs: engine-specific config (api_key, base_url, model, bot_instance)
        """
        self.engine = engine.lower()
        self.bot: Optional[Bot] = kwargs.get("bot_instance")
        
        # OpenAI API config
        self.openai_client = None
        self.model = kwargs.get("model", "gpt-4")
        if self.engine == "openai":
            self.openai_client = OpenAI(
                api_key=kwargs.get("api_key"),
                base_url=kwargs.get("base_url")
            )

    def call(self, prompt: str, system_message: str = "You are a strict data extraction engine.") -> str:
        """Raw call to the underlying engine."""
        if self.engine == "openai":
            return self._call_openai(prompt, system_message)
        elif self.engine == "selenium":
            if not self.bot:
                raise RuntimeError("Bot instance required for Selenium engine.")
            return self.bot.send_prompt_and_get_response(prompt)
        else:
            raise ValueError(f"Unknown engine: {self.engine}")

    def _call_openai(self, prompt: str, system_message: str) -> str:
        if not self.openai_client:
            raise RuntimeError("OpenAI client not initialized.")
        try:
            response = self.openai_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"OpenAI API call failed: {e}")
            return ""

    # -- Specific Tasks --

    def generate_description(self, content: str) -> str:
        """Generate a professional business description from raw content."""
        prompt = f"""
        Write a professional 250-word business description based on the content below.
        
        STRICT RULES:
        - No intro lines (e.g. "Here is a summary...")
        - No fluff or boilerplate
        - No 'Overview' or 'Summary' headings
        - Start directly with the business's core value proposition
        - Maintain a highly professional, objective tone
        
        CONTENT:
        {content[:12000]}
        
        OUTPUT:
        Return ONLY plain text.
        """
        return self.call(prompt, system_message="You are an expert business analyst.")

    def extract_metadata(
        self, 
        title: str, 
        description: str, 
        needs_tagging: bool = True, 
        needs_entities: bool = True
    ) -> Dict[str, Any]:
        """
        Extract entities, sectors, and channels in a single pass.
        Returns a dict with 'entities', 'sectors', and 'channel'.
        """
        if not needs_tagging and not needs_entities:
            return {}

        schema_fields = []
        task_parts = []

        if needs_entities:
            task_parts.append(
                "TASK 1 -- ENTITY EXTRACTION:\n"
                "Extract named entities explicitly mentioned in the text.\n"
                "Focus on: organizations/startups, people, locations, institutions, investors.\n"
                "- Preserve exact casing.\n"
                "- No duplicates, no products, no monetary values.\n"
            )
            schema_fields.append('"entities": [{"name": "string", "type": "string"}]')

        if needs_tagging:
            channels_str = ", ".join(f'"{k}": "{v}"' for k, v in CHANNELS_MAP.items())
            sectors_str = ", ".join(f'"{s}"' for s in SECTORS_LIST)
            task_parts.append(
                f"TASK 2 -- CHANNEL CLASSIFICATION:\n"
                f"Select at most 2 channels from: {{{channels_str}}}\n\n"
                f"TASK 3 -- SECTOR CLASSIFICATION:\n"
                f"Select at most 5 sectors from: [{sectors_str}]\n"
            )
            schema_fields.append('"channel": {"key": "Value"}')
            schema_fields.append('"sectors": ["Sector Name"]')

        schema = "{" + ", ".join(schema_fields) + "}"
        
        prompt = f"""
        Extract requested data from the news snippet below.
        
        RULES:
        - Return ONLY strict JSON.
        - No markdown code blocks, no explanation.
        - If Uncertain, omit.
        
        TASKS:
        {"".join(task_parts)}
        
        OUTPUT FORMAT:
        {schema}
        
        INPUT:
        Title: {title}
        Description: {description[:1000]}
        """
        
        raw = self.call(prompt)
        return self._parse_json(raw, needs_tagging, needs_entities)

    def _parse_json(self, raw: str, needs_tagging: bool, needs_entities: bool) -> Dict[str, Any]:
        """Robustly parse JSON response from LLM."""
        if not raw:
            return {}

        # Cleanup markdown fences
        cleaned = re.sub(r'```(?:json)?', '', raw).strip('`').strip()
        
        data = {}
        try:
            data = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            # Fallback for nested JSON
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except:
                    pass

        if not isinstance(data, dict):
            return {}

        result = {}
        if needs_entities:
            entities = data.get("entities", [])
            result["entities"] = [e for e in entities if isinstance(e, dict) and "name" in e] if isinstance(entities, list) else []

        if needs_tagging:
            # Channels
            raw_channel = data.get("channel", {})
            if isinstance(raw_channel, dict):
                result["channel"] = {k: v for k, v in raw_channel.items() if k in CHANNELS_MAP}
            else:
                result["channel"] = {}

            # Sectors
            raw_sectors = data.get("sectors", [])
            if isinstance(raw_sectors, list):
                result["sectors"] = [s for s in raw_sectors if s in SECTORS_LIST]
            else:
                result["sectors"] = []

        return result