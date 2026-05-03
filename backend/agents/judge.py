import json
import os
import re
from typing import Dict, List, Tuple, Any
from dataclasses import dataclass
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ.get("OPENROUTER_API_KEY"),
)

# --- Configuration: Source Trust and Bias Scores ---
# Trust (T): 0.0 to 1.0 (1.0 = highly reliable)
# Bias (B): -1.0 to 1.0 (-1.0 = Left, 1.0 = Right, 0 = Neutral)
import csv

# Trusted datasets and predefined sources have T=1.0 and B=0.0 (Neutral).
SOURCE_METRICS = {
    # Universal Fact Checkers
    "PolitiFact": {"trust": 1.0, "bias": 0.0},
    "FactCheck.org": {"trust": 1.0, "bias": 0.0},
    "Snopes": {"trust": 1.0, "bias": 0.0},
    "Associated Press Fact Check": {"trust": 1.0, "bias": 0.0},
    "Associated Press": {"trust": 1.0, "bias": 0.0},
    "Reuters Fact Check": {"trust": 1.0, "bias": 0.0},
    "Reuters": {"trust": 1.0, "bias": 0.0},
    "Washington Post Fact Checker": {"trust": 1.0, "bias": 0.0},

    # Healthcare
    "BLS": {"trust": 1.0, "bias": 0.0},
    "CDC": {"trust": 1.0, "bias": 0.0},
    "NIH": {"trust": 1.0, "bias": 0.0},
    "WHO": {"trust": 1.0, "bias": 0.0},
    "KFF": {"trust": 1.0, "bias": 0.0},

    # Immigration
    "USCIS": {"trust": 1.0, "bias": 0.0},
    "Migration Policy Institute": {"trust": 1.0, "bias": 0.0},
    "Pew Research": {"trust": 1.0, "bias": 0.0},
    "UNHCR": {"trust": 1.0, "bias": 0.0},
    "Customs and Border Protection": {"trust": 1.0, "bias": 0.0},

    # Crime
    "BJS": {"trust": 1.0, "bias": 0.0},
    "FBI": {"trust": 1.0, "bias": 0.0},
    "NIJ": {"trust": 1.0, "bias": 0.0},

    # Economy
    "BEA": {"trust": 1.0, "bias": 0.0},
    "FRED": {"trust": 1.0, "bias": 0.0},
    "Census Bureau": {"trust": 1.0, "bias": 0.0},
    "OECD": {"trust": 1.0, "bias": 0.0},

    # Education
    "NCES": {"trust": 1.0, "bias": 0.0},
}

def load_news_sources():
    """Loads news sources from the parsed AllSides CSV dataset."""
    # Assuming judge.py is in backend/agents/ and csv is in backend/data/
    csv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "media_bias.csv")
    
    if not os.path.exists(csv_path):
        print(f"Warning: News bias dataset not found at {csv_path}")
        return
        
    bias_mapping = {
        "Left": -1.0,
        "Lean Left": -0.5,
        "Center": 0.0,
        "Lean Right": 0.5,
        "Right": 1.0
    }
    
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                source = row.get("News Source", "").strip()
                rating = row.get("AllSides Bias Rating", "").strip()
                
                if source and rating:
                    bias_val = bias_mapping.get(rating, 0.0)
                    
                    # Only add if it's not already defined as a trusted dataset/fact checker
                    if source not in SOURCE_METRICS:
                        SOURCE_METRICS[source] = {"trust": 0.50, "bias": bias_val}
    except Exception as e:
        print(f"Error loading media bias CSV: {e}")

# Populate news sources at module import
load_news_sources()
SOURCE_METRICS["Default"] = {"trust": 0.50, "bias": 0.0}

@dataclass
class NLIResult:
    p_entail: float
    p_contradict: float

async def get_nli_probabilities(claim: str, evidence: str) -> NLIResult:
    """
    Uses an LLM to simulate an NLI model, returning probabilities for entailment and contradiction.
    """
    system_prompt = """
    You are a logical verification system (Natural Language Inference).
    Given a claim and a piece of evidence, determine the probability that the evidence entails (supports) the claim, 
    and the probability that it contradicts (refutes) the claim.
    
    Respond STRICTLY in JSON format with two keys: "p_entail" and "p_contradict".
    Both values should be floats between 0.0 and 1.0.
    """
    
    user_prompt = f"Claim: {claim}\n\nEvidence: {evidence}"
    
    try:
        response = await client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            extra_headers={
                "HTTP-Referer": "http://localhost:8000",
                "X-Title": "BeaverHacks Fact-Checker",
            }
        )
        
        content = response.choices[0].message.content
        
        # Clean markdown if present
        content = re.sub(r'```json\n?(.*?)\n?```', r'\1', content, flags=re.DOTALL)
        content = re.sub(r'```\n?(.*?)\n?```', r'\1', content, flags=re.DOTALL)
        content = content.strip()
        
        data = json.loads(content)
        return NLIResult(p_entail=data.get("p_entail", 0.0), p_contradict=data.get("p_contradict", 0.0))
        
    except Exception as e:
        print(f"Error parsing NLI response: {e}")
        # Default to neutral if it fails
        return NLIResult(p_entail=0.0, p_contradict=0.0)

def match_source_metrics(source_name: str) -> Tuple[float, float]:
    """Finds the trust and bias metrics for a given source string."""
    # Catch any .gov sites automatically
    if ".gov" in source_name.lower():
        return 1.0, 0.0

    for key, metrics in SOURCE_METRICS.items():
        if key.lower() in source_name.lower():
            return metrics["trust"], metrics["bias"]
    return SOURCE_METRICS["Default"]["trust"], SOURCE_METRICS["Default"]["bias"]

async def extract_evidence_items(markdown_text: str) -> List[Dict[str, str]]:
    """
    Parses unstructured markdown text from a domain agent into a structured list of evidence items.
    Returns: [{"source": "Source Name", "text": "The exact fact/evidence stated"}]
    """
    system_prompt = """
    You are a data extraction assistant. 
    Your job is to read the provided markdown text and extract all specific pieces of evidence and their corresponding sources.
    
    Respond STRICTLY in JSON format as a list of dictionaries. Each dictionary must have two keys: "source" and "text".
    - "source": The name of the organization, dataset, or publication providing the fact (e.g., "FBI", "CDC", "New York Times").
    - "text": A concise summary of the factual claim or statistic provided by that source.
    
    If no clear sources or facts are found, return an empty list [].
    """
    
    try:
        response = await client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Extract evidence from this text:\n\n{markdown_text}"}
            ],
            extra_headers={
                "HTTP-Referer": "http://localhost:8000",
                "X-Title": "BeaverHacks Fact-Checker",
            }
        )
        
        content = response.choices[0].message.content
        
        # Clean markdown if present
        content = re.sub(r'```json\n?(.*?)\n?```', r'\1', content, flags=re.DOTALL)
        content = re.sub(r'```\n?(.*?)\n?```', r'\1', content, flags=re.DOTALL)
        content = content.strip()
        
        data = json.loads(content)
        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and "evidence" in data:
            return data["evidence"]
        else:
            return []
            
    except Exception as e:
        print(f"Error extracting evidence: {e}")
        return []

async def calculate_confidence(claim: str, evidence_items: List[Dict[str, str]], bias_lambda: float = 0.2, source_bonus_alpha: float = 0.1) -> Dict[str, Any]:
    """
    Runs the verification math algorithm.
    evidence_items is a list of dicts: [{"source": "CDC", "text": "The text..."}]
    """
    import math
    
    if not evidence_items:
        return {"final_score": 0.0, "verdict": "Unverified", "reasoning": "No evidence provided."}

    total_weighted_evidence = 0.0
    total_trust = 0.0
    total_bias = 0.0
    
    n_sources = len(evidence_items)
    
    details = []

    for item in evidence_items:
        source = item.get("source", "Unknown")
        text = item.get("text", "")
        
        # 1. Get Metrics
        trust, bias = match_source_metrics(source)
        
        # 2. Get NLI Probabilities
        nli = await get_nli_probabilities(claim, text)
        
        # 3. Calculate Evidence Score for this source
        e_i = nli.p_entail - nli.p_contradict
        
        total_weighted_evidence += (e_i * trust)
        total_trust += trust
        total_bias += bias
        
        details.append({
            "source": source,
            "trust": trust,
            "bias": bias,
            "p_entail": nli.p_entail,
            "p_contradict": nli.p_contradict,
            "evidence_score": e_i
        })
        
    # 4. Aggregation
    wes = total_weighted_evidence / total_trust if total_trust > 0 else 0.0
    
    # 5. Bias Adjustment
    avg_bias = total_bias / n_sources
    bias_penalty = bias_lambda * abs(avg_bias)
    
    # 6. Final Score
    # Give a small logarithmic bonus for having more distinct sources, capped.
    source_bonus = 1 + (source_bonus_alpha * math.log(n_sources)) if n_sources > 0 else 1.0
    
    final_score = wes * (1 - bias_penalty) * source_bonus
    
    # Cap between -1.0 and 1.0
    final_score = max(-1.0, min(1.0, final_score))
    
    # 7. Determine Verdict
    verdict = "Unverified / Needs Context"
    if final_score > 0.6:
        verdict = "True"
    elif final_score < -0.6:
        verdict = "False"
        
    warning = ""
    if bias_penalty > 0.15:
        warning = "Warning: High source bias detected. Corroboration needed across more diverse sources."

    return {
        "final_score": round(final_score, 3),
        "verdict": verdict,
        "wes": round(wes, 3),
        "average_bias": round(avg_bias, 3),
        "bias_penalty": round(bias_penalty, 3),
        "warning": warning,
        "details": details
    }
