import logging
import time
import re
import json
import datetime
import requests
from pymongo import MongoClient, UpdateOne
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from openai import AzureOpenAI

MONGO_URI   = 'mongodb://admin9:i38kjmx35@94.130.33.235:27017/?authSource=admin&directConnection=true&tls=true&tlsAllowInvalidCertificates=true&tlsAllowInvalidHostnames=true'
endpoint     = "https://ai-llmmodeldeployment653596309444.openai.azure.com/"
MODEL       = "gpt-5.1-chat"
BATCH_WRITE = 20
MAX_WORKERS = 20
MAX_RETRIES = 3


subscription_key = ""
api_version = "2024-12-01-preview"
client = AzureOpenAI(
    api_version=api_version,
    azure_endpoint=endpoint,
    api_key=subscription_key,
)

CHANNELS_MAP = {
    "ch-funding":      "Funding & Raises",
    "ch-partnerships": "Partnerships & Alliances",
    "ch-ma":           "M&A Activity",
    "ch-investments":  "Strategic Investments",
    "ch-gov-policy":   "Government & Policy",
    "ch-company-news": "Company News & Product Launches",
    "ch-regulatory":   "Regulatory Milestones"
}

SECTORS_LIST = [
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

logging.basicConfig(
    filename="tagger.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

lock            = Lock()
processed_count = 0
error_count     = 0


# def call_llm(prompt: str, seed: int = None) -> str:
#     payload = {
#         "model": MODEL,
#         "messages": [{"role": "user", "content": prompt}],
#         "stream": False,
#         "temperature": 0.0,
#     }
#     if seed is not None:
#         payload["seed"] = seed

#     for attempt in range(MAX_RETRIES):
#         try:
#             response = requests.post(LLM_URL, json=payload)
#             return response.json()["choices"][0]["message"]["content"].strip()
#         except Exception as e:
#             logger.warning(f"LLM attempt {attempt+1} failed: {e}")
#             time.sleep(2 ** attempt)
#     return ""

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

def call_llm(prompt: str) -> str:
    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": prompt}
                ]
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"LLM attempt {attempt+1} failed: {e}")
            time.sleep(2 ** attempt)
    return ""


def classify_entities(title: str, description: str) -> list:
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
        Output ONLY valid JSON in this exact format -- no markdown, no explanation, nothing else
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
        Description: {description}
    """
    raw = call_llm(prompt)
    raw = re.sub(r'```(?:json)?', '', raw).strip()

    if not raw or raw.upper() == "NONE":
        return []

    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("entities", [])
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
                if isinstance(parsed, dict):
                    return parsed.get("entities", [])
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass

    logger.warning(f"Entity parse failed for title='{title[:60]}': {raw[:200]}")
    return []


def classify_channel(title: str, description: str) -> dict:
    channels_str = "\n".join([f"  {k}: {v}" for k, v in CHANNELS_MAP.items()])

    prompt = f"""You are a financial news channel tagging agent.

        Task:
        - Carefully read the news title and description below.
        - Select ONLY the most relevant channel(s) that describe the TYPE of this news event.
        - You may select AT MOST 2 channels. Select 1 if only one clearly fits.
        - These are EVENT TYPE categories — not industries or company names.
        - If no channel clearly applies, output: NONE

        Allowed channels ( a dict in a python ):
        {CHANNELS_MAP}

        OUTPUT RULES:
        - Output ONLY valid JSON in this exact format -- no markdown, no explanation, nothing else
        - These channels are as the dict formate and you need to give me the key of relative channels
        - Output channel keys only, one per line.
        - NO extra text, NO explanations, NO headings, NO bullet points.
        - If nothing fits, output the single word: NONE
        Title: {title}
        Description: {description[:600]}
    """
    raw = call_llm(prompt)
    raw = re.sub(r'\*+', '', raw).strip()

    if not raw or raw.upper() == "NONE":
        return {}

    channel = {}
    for line in raw.split("\n"):
        key = line.strip().lower()
        if key in CHANNELS_MAP:
            channel[key] = CHANNELS_MAP[key]
        if len(channel) == 2:
            break

    return channel


def classify_sectors(title: str, description: str) -> list:
    sectors_str = "\n".join([f"  {s}" for s in SECTORS_LIST])

    prompt = f"""You are a financial news sector tagging agent.

        Task:
        - Carefully read the news title and description below.
        - Select ONLY the most relevant industry sectors from the allowed list below.
        - Focus on the CORE industry this news belongs to.
        - You may select AT MOST 5 sectors. Select fewer if only 1 or 2 clearly apply.
        - If no sector clearly applies, output: NONE

        Allowed sectors (copy names EXACTLY as shown — spelling, spacing, capitalisation must match):
        {sectors_str}

        OUTPUT RULES:
        - Output ONLY valid JSON in this exact format -- no markdown, no explanation, nothing else
        - One sector name per line, copied exactly from the allowed list above.
        - NO extra text, NO explanations, NO headings, NO bullet points.
        - NEVER invent or paraphrase sector names. If it is not in the list, do not use it.
        - If nothing fits, output the single word: NONE
        Title: {title}
        Description: {description[:400]}
    """

    raw = call_llm(prompt)
    raw = re.sub(r'\*+', '', raw).strip()

    if not raw or raw.upper() == "NONE":
        return []

    sectors = []
    for line in raw.split("\n"):
        s = line.strip()
        if s in SECTORS_LIST:
            sectors.append(s)
        if len(sectors) == 5:
            break

    return sectors


def process_doc(doc: dict) -> UpdateOne | None:
    global processed_count, error_count
    try:
        raw_desc = doc.get("description", "")
        if isinstance(raw_desc, dict):
            description = raw_desc.get("details", "") or raw_desc.get("summary", "")
        else:
            description = raw_desc or ""

        title = doc.get("title", "")

        needs_tagging  = not (doc.get("channel") and doc.get("sectors"))
        entity_status  = doc.get("llm_tagged_entities", 0)
        needs_entities = entity_status != 2

        update_fields = {}
        t0 = time.time()

        if needs_tagging and needs_entities:
            with ThreadPoolExecutor(max_workers=3) as ex:
                f_channel  = ex.submit(classify_channel,  title, description)
                f_sectors  = ex.submit(classify_sectors,  title, description)
                f_entities = ex.submit(classify_entities, title, description)
                channel  = f_channel.result()
                sectors  = f_sectors.result()
                entities = f_entities.result()

            update_fields.update({
                "channel":             channel,
                "sectors":             sectors,
                "llm_tagged":          True,
                "entities":            entities,
                "llm_tagged_entities": 2
            })

        elif needs_tagging:
            with ThreadPoolExecutor(max_workers=2) as ex:
                f_channel = ex.submit(classify_channel, title, description)
                f_sectors = ex.submit(classify_sectors, title, description)
                channel = f_channel.result()
                sectors = f_sectors.result()

            update_fields.update({
                "channel":    channel,
                "sectors":    sectors,
                "llm_tagged": True
            })

        elif needs_entities:
            entities = classify_entities(title, description)
            update_fields.update({
                "entities":            entities,
                "llm_tagged_entities": 2
            })

        total = round(time.time() - t0, 2)
        print(f"{datetime.datetime.now()} | ID: {doc['_id']} | TOTAL: {total}s")
        logger.info(f"ID: {doc['_id']} | total: {total}s")
        with lock:
            processed_count += 1

        if not update_fields:
            return None

        return UpdateOne({"_id": doc["_id"]}, {"$set": update_fields})

    except Exception as e:
        with lock:
            error_count += 1
        logger.error(f"Doc error {doc.get('_id')}: {e}")
        return None

FETCH_BATCH = 50
def run():
    client     = MongoClient(MONGO_URI)
    collection = client['NEWSSCRAPERDATA']['MAIN_NEWS_ALL']

    projection = {"_id": 1, "title": 1, "description": 1, "llm_tagged": 1, "llm_tagged_entities": 1, "channel": 1, "sectors": 1}

    queries = [
        # P1: completely untouched
        {
            "llm_tagged":          {"$ne": True},
            "llm_tagged_entities": {"$nin": [1, 2]}
        },
        # P2: channels/sectors done, entities missing
        {
            "llm_tagged":          True,
            "llm_tagged_entities": {"$nin": [1, 2]}
        },
        # P3: re-pass old rules
        {
            "llm_tagged_entities": 1
        },
    ]

    start = time.time()

    for p_index, query in enumerate(queries, start=1):
        total = collection.count_documents(query)

        if total == 0:
            print(f"⏭P{p_index}: nothing to process, skipping.")
            continue

        print(f"\nP{p_index}: {total} documents to process.")
        logger.info(f"P{p_index}: {total} docs")

        skip     = 0
        bulk_ops = []

        while True:
            batch = list(
                collection.find(query, projection)
                .sort("time", -1)
                .skip(skip)
                .limit(FETCH_BATCH)
            )

            if not batch:
                print(f"P{p_index}: all batches done.")
                break

            print(f"P{p_index} | Fetched batch: {skip} → {skip + len(batch)}")

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {executor.submit(process_doc, doc): doc for doc in batch}

                for future in as_completed(futures):
                    op = future.result()
                    if op:
                        bulk_ops.append(op)

                    if len(bulk_ops) >= BATCH_WRITE:
                        collection.bulk_write(bulk_ops, ordered=False)
                        bulk_ops.clear()
                        elapsed = time.time() - start
                        rate    = processed_count / elapsed if elapsed > 0 else 0
                        eta     = (total - processed_count) / rate if rate > 0 else 0
                        msg = (
                            f"Written | P{p_index} | {processed_count}/{total} | "
                            f"Errors: {error_count} | "
                            f"{rate:.1f} docs/sec | "
                            f"ETA: {eta/60:.1f} min"
                        )
                        print(msg)
                        logger.info(msg)

            if bulk_ops:
                collection.bulk_write(bulk_ops, ordered=False)
                bulk_ops.clear()

            skip += FETCH_BATCH

    elapsed = time.time() - start
    msg = (
        f"Done | Processed: {processed_count} | "
        f"Errors: {error_count} | "
        f"Time: {elapsed/60:.1f} min"
    )
    print(f"\n{msg}")
    logger.info(msg)
    client.close()


if __name__ == "__main__":
    run()