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
        self.sectors_list = [
            "Marketing & Ad Tech", "Agriculture", "Retail", "Enterprise Infrastructure",
            "GenerativeAI", "Healthcare", "Hospitality", "Robotics", "Metaverse",
            "Advanced Materials", "Legal", "Sustainability Tech", "Fashion Tech",
            "Chemicals and Materials Tech", "Nanotechnology", "AI Infrastructure",
            "Manufacturing", "Beauty Tech", "Quantum Computing", "Virtual Reality",
            "Finance", "F&B", "Drone-Tech", "Geographic Information Systems",
            "Education", "Enterprise Software", "Construction Tech", "Energy",
            "Sports", "IOT", "Blockchain Infrastructure", "Telecom", "Space Tech",
            "HR Tech", "Cyber Security", "Real Estate Tech", "Transportation",
            "Mining", "Augmented Reality"
        ]
        self.channels_mapping = {
            "ch-funding":      "Funding & Raises",
            "ch-partnerships": "Partnerships & Alliances",
            "ch-ma":           "M&A Activity",
            "ch-investments":  "Strategic Investments",
            "ch-gov-policy":   "Government & Policy",
            "ch-company-news": "Company News & Product Launches",
            "ch-regulatory":   "Regulatory Milestones"
        }
        self.sectors_str = "\n".join([f"  {s}" for s in self.sectors_list])
        self.channels_str = "\n".join([f"  {k}: {v}" for k, v in self.channels_mapping.items()])


    def call_llm(self,prompt: str) -> str:
        if self.small_llm:
            return call_8b_llm(prompt)
        else:
            return call_120b_llm(prompt)
    
    def get_sectors(self, title : str, descriptions : str) -> dict:
        prompt = f"""
            You are a financial news sector tagging agent.

            Task:
            - Carefully read the news title and description below.
            - Select ONLY the most relevant industry sectors from the allowed list below.
            - Focus on the CORE industry this news belongs to.
            - You may select AT MOST 5 sectors. Select fewer if only 1 or 2 clearly apply.

            Allowed sectors (copy names EXACTLY as shown — spelling, spacing, capitalisation must match):
            {self.sectors_str}

            OUTPUT RULES:
            - One sector name per line, copied exactly from the allowed list above.
            - NO extra text, NO explanations, NO headings, NO bullet points.
            - NEVER invent or paraphrase sector names. If it is not in the list, do not use it.
            - If nothing fits, output the single word: NONE
            - only return as dict with key "sectors" and value as list of sectors. Do not include any other text.

            Title: {title}
            Description: {descriptions[:600] if len(descriptions) > 600 else descriptions}
        """

        response = self.call_llm(prompt)
        try:
            sectors = [ sector for sector in response.get("sectors", []) if sector in self.sectors_list ]
            return {"sectors": sectors}
        except Exception as e:
            logger.error(f"Error parsing LLM response: {e}")

        return {"sectors": []}
    
    def get_channels(self, title : str, descriptions : str) -> dict:
        prompt = f"""
            You are a financial news sector tagging agent.

            Task:
            - Carefully read the news title and description below.
            - Select ONLY the most relevant channel(s) that describe the TYPE of this news event.
            - You may select AT MOST 2 channels. Select 1 if only one clearly fits.
            - These are EVENT TYPE categories — not industries or company names.

            Allowed channels ( a dict in a python ):
            {self.channels_str}

            OUTPUT RULES:
            - These channels are as the dict formate and you need to give me the key of relative channels
            - Output channel keys only, one per line.
            - NO extra text, NO explanations, NO headings, NO bullet points.
            - If nothing fits, output the empty list: []
            - only return as dict with key "channels" and value as list of channels. Do not include any other text.

            Title: {title}
            Description: {descriptions[:600] if len(descriptions) > 600 else descriptions}
        """

        response = self.call_llm(prompt)
        try:
            channels = [ channel for channel in response.get("channels", []) if channel in self.channels_mapping ]
            return {"channels": channels}
        except Exception as e:
            logger.error(f"Error parsing LLM response: {e}")

        return {"channels": []}
    
    def get_entities(self, title : str, descriptions : str) -> dict:
        prompt = f"""
            You are a precise news entity extraction API.

            Your job is to extract named entities explicitly mentioned in the input text.

            Scope:
            - Focus primarily on organizations/startups.
            - Also extract other named entities when clearly present.

            Allowed entity types:
            - organization/startup
            - person
            - location
            - institution
            - investor

            Rules:
                1. Extract ONLY entities explicitly named in the text. Never infer, guess, or use external knowledge.
                2. Preserve exact casing as written in the source text.
                3. If both full name and abbreviation appear, keep ONLY the full name (e.g. keep "U.S. Securities and Exchange Commission", drop "SEC").
                4. Extract each entity only once. No duplicates.
                5. When unsure about any entity, skip it. Precision over recall.
                6. Do NOT extract product names, service names, or generic words.
                7. Use the most specific type when an entity fits multiple (e.g. "Harvard University" → institution, not location).
                8. Extract country names, city names, and regions as location type, even when used as geopolitical actors (e.g. "US", "Iran").
                9. If no entities are found, return an empty list.
                10. Output must be strict valid JSON only. No markdown, no explanation, no extra text.
                11. Never extract monetary values, percentages, or numbers as entities (e.g. "$50M", "10%", "2024").
                12. Never extract job titles or roles as entities (e.g. "CEO", "Chairman", "Founder") — only the person's actual name.
                13. Never extract time references as entities (e.g. "Q3", "Monday", "this year", "2024").
                14. If an entity is only implied by a pronoun (e.g. "he", "they", "it"), do not extract it.
                15. Never extract industry terms or sector names as entities (e.g. "fintech", "AI", "crypto", "SaaS").
                16. If a location is part of a company name, do not extract it separately (e.g. in "Bank of America", do not extract "America" as a location).
                17. Never extract adjectives derived from entity names as entities (e.g. "American", "Chinese", "Israeli").
                18. If a person is referenced only by their last name or first name alone, extract it only if it is completely unambiguous from context.
                19. Never extract hypothetical or speculative entities (e.g. "a potential acquirer", "an unnamed investor").
                20. Never extract entities from quoted speech that are not real-world entities (e.g. metaphors, analogies).

            Return exactly this schema:
            {{"entities": [{{"name": "string", "type": "organization"}}]}}

            Input text:
            Title: {title}
            Description: {descriptions}
        """

        response = self.call_llm(prompt)
        try:
            entities = response.get("entities", [])
            return {"entities": entities}
        except Exception as e:
            logger.error(f"Error parsing LLM response: {e}")

        return {"entities": []}
    
    def get_all(self, title: str, descriptions: str) -> dict:
        prompt = f"""
        You are a financial news analysis API. Given a news title and description, you must extract three things simultaneously and return ONLY a single valid JSON object — no markdown, no explanation, no extra text.

        ===== TASK 1: SECTORS =====
        Select the most relevant industry sectors from the allowed list.
        - Max 5 sectors. Select fewer if only 1–2 clearly apply.
        - Focus on the CORE industry this news belongs to.
        - You may select AT MOST 5 sectors. Select fewer if only 1 or 2 clearly apply.
        - Copy names EXACTLY as listed (spelling, spacing, capitalisation must match).
        - If nothing fits → empty list.

        Allowed sectors:
        {self.sectors_str}

        ===== TASK 2: CHANNELS =====
        Select the most relevant channel keys that describe the TYPE of this news event.
        - Max 2 channels. Select 1 if only one clearly fits.
        - Output the channel KEY (e.g. "ch-funding"), not the label.
        - If nothing fits → empty list.

        Allowed channels:
        {self.channels_str}

        ===== TASK 3: ENTITIES =====
        Extract named entities explicitly mentioned in the text.

        Allowed types: organization/startup, person, location, institution, investor

        Rules:
        - Extract ONLY entities explicitly named. Never infer or guess.
        - Preserve exact casing from source text.
        - If full name and abbreviation both appear, keep only the full name.
        - No duplicates.
        - Do NOT extract: product names, monetary values, percentages, numbers, job titles/roles, time references (Q3, Monday, 2024), pronouns, industry terms (AI, fintech, SaaS), adjectives from entity names (American, Chinese), hypothetical entities, or locations that are part of a company name.
        - Use most specific type (e.g. "Harvard University" → institution, not location).
        - Extract country/city/region names as location type.
        - If nothing found → empty list.

        ===== OUTPUT FORMAT (strict) =====
        Return ONLY this JSON and nothing else:
        {{
        "sectors": ["<sector name>", ...],
        "channels": ["<channel key>", ...],
        "entities": [
            {{"name": "<exact name>", "type": "<entity type>"}},
            ...
        ]
        }}

        ===== INPUT =====
        Title: {title}
        Description: {descriptions}
        """

        response = self.call_llm(prompt)
        try:
            sectors = [s for s in response.get("sectors", []) if s in self.sectors_list]
            channels = [c for c in response.get("channels", []) if c in self.channels_mapping]
            entities = response.get("entities", [])
            if not isinstance(entities, list):
                entities = []

            return {
                "sectors": sectors,
                "channels": channels,
                "entities": entities
            }
        except Exception as e:
            logger.error(f"Error parsing get_all LLM response: {e}")
            return {
                "sectors": [],
                "channels": [],
                "entities": []
            }

    def test_import(self):
        logger.info("SmallLLM import successful!")
        return "SmallLLM import successful!"