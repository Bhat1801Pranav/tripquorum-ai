import os
import re
import json
import time
import urllib.parse
from typing import List, Dict, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from google import genai
from google.genai import types
from sqlalchemy import create_engine, text

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tripquorum.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)

app = FastAPI(title="TripQuorum AI - Multi-Agent Group Trip & Highway Micro-Itinerary Engine")

def init_db():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS trips (
                room_code TEXT PRIMARY KEY,
                trip_name TEXT,
                planning_mode TEXT,
                origin_city TEXT,
                target_destination TEXT,
                trip_duration TEXT,
                must_visit_spots TEXT,
                created_at REAL,
                gen_count INTEGER DEFAULT 0,
                last_gen_time REAL DEFAULT 0
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS preferences (
                room_code TEXT,
                user_name TEXT,
                max_budget_inr INTEGER,
                preferred_dates TEXT,
                dietary_pref TEXT,
                vibe TEXT,
                transport_pref TEXT,
                dealbreakers TEXT,
                PRIMARY KEY (room_code, user_name)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS proposals (
                room_code TEXT PRIMARY KEY,
                prompt_version TEXT,
                model_used TEXT,
                proposals_json TEXT,
                latency_ms REAL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS votes (
                room_code TEXT,
                user_name TEXT,
                ranked_choices_json TEXT,
                PRIMARY KEY (room_code, user_name)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS micro_itineraries (
                room_code TEXT PRIMARY KEY,
                winning_option TEXT,
                model_used TEXT,
                itinerary_json TEXT,
                latency_ms REAL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                room_code TEXT,
                task_type TEXT,
                prompt_version TEXT,
                model_used TEXT,
                latency_ms REAL,
                estimated_tokens INTEGER,
                status TEXT
            )
        """ if DATABASE_URL.startswith("sqlite") else """
            CREATE TABLE IF NOT EXISTS telemetry (
                id SERIAL PRIMARY KEY,
                timestamp DOUBLE PRECISION,
                room_code TEXT,
                task_type TEXT,
                prompt_version TEXT,
                model_used TEXT,
                latency_ms DOUBLE PRECISION,
                estimated_tokens INTEGER,
                status TEXT
            )
        """))

init_db()

PROMPT_REGISTRY = {
    "v1_vibe_balanced": """You are an expert Indian Road-Trip & Group Travel Mediator AI.
Planning Mode: {planning_mode}
Origin City: {origin_city}
Target Destination / Region: {target_destination}
Trip Duration: {trip_duration}
Host Must-Visit Local Spots: {must_visit_spots}
STRICT GROUP DIETARY RULE: {group_dietary_rule}

Participant Preferences & Constraints:
{preferences_text}

INSTRUCTIONS:
- Propose EXACTLY 4 distinct Route & Vibe Itinerary Packages in and around {target_destination} (incorporating {must_visit_spots} if provided).
- Never exceed the lowest member budget cap (INR {strict_budget_cap}).
- Respect the strict dietary rule ({group_dietary_rule}) and highway feasibility.

Return ONLY a valid JSON array of 4 objects matching this exact schema:
[
  {{
    "option_title": "Name of Destination OR Route Package Title",
    "estimated_cost_per_person_inr": 4200,
    "best_dates": "Recommended date/time window",
    "travel_mode": "Sleeper Bus / Car / Train",
    "route_highway_summary": "Main highway (e.g., NH-48) & realistic travel time",
    "veg_food_feasibility": "How Pure Veg / dietary needs are handled on this route",
    "why_it_fits_group": "2-sentence explanation resolving member vibes & budgets",
    "key_highlights": ["Spot 1", "Spot 2", "Spot 3"],
    "compromise_note": "Any minor trade-off a member makes"
  }}
]""",

    "v2_budget_highway_strict": """You are a Strict Budget, Highway Logistics & Dietary Compliance Travel Optimizer AI.
Planning Mode: {planning_mode}
Origin City: {origin_city}
Target Destination / Region: {target_destination}
Trip Duration: {trip_duration}
Host Must-Visit Local Spots: {must_visit_spots}
STRICT GROUP DIETARY RULE: {group_dietary_rule}

Participant Preferences & Constraints:
{preferences_text}

CRITICAL RULES:
1. HARD BUDGET CAP: Total per-person cost MUST stay strictly at or below INR {strict_budget_cap}.
2. DIETARY SAFETY: {group_dietary_rule}. Explicitly verify vegetarian availability along the highway corridor.
3. Propose EXACTLY 4 distinct options.

Return ONLY a valid JSON array of 4 objects matching this exact schema:
[
  {{
    "option_title": "Name of Destination OR Route Package Title",
    "estimated_cost_per_person_inr": 3800,
    "best_dates": "Recommended date/time window",
    "travel_mode": "Sleeper Bus / Car / Train",
    "route_highway_summary": "Exact highway corridor & travel duration",
    "veg_food_feasibility": "Verified Pure Veg dhaba/hotel availability along this corridor",
    "why_it_fits_group": "Detailed cost + logistics fit for the group",
    "key_highlights": ["Spot 1", "Spot 2", "Spot 3"],
    "compromise_note": "How this keeps costs strictly under INR {strict_budget_cap}"
  }}
]"""
}

MICRO_ITINERARY_PROMPT = """You are a Real-Time Highway & Micro-Itinerary Navigation Agent for India.
Origin City: {origin_city}
Selected Destination / Route: {winning_option}
Trip Duration: {trip_duration}
Host Must-Visit Spots: {must_visit_spots}
Strict Group Budget Cap: INR {strict_budget_cap} per person
STRICT DIETARY REQUIREMENT: {group_dietary_rule}
Group Member Details:
{preferences_text}

CRITICAL INSTRUCTIONS:
1. Build a concise, chronological timeline of 8 to 10 key stops covering highway departure, verified Pure Veg Breakfast, Sightseeing Spots, Highway Pure Veg Lunch, Afternoon/Sunset Spots, and Dinner.
2. EVERY meal stop MUST name a REAL verified Pure Veg restaurant/hotel along that route (e.g., on NH-48 / Uttara Kannada highway corridor).
3. HIGHWAY-SIDE CUES: Specify left/right highway positioning cues and landmarks.
4. Keep descriptions concise so the response generates quickly.

Return ONLY valid JSON matching this exact structure:
{{
  "itinerary_title": "Complete Highway & Micro-Itinerary Plan for {winning_option}",
  "dietary_compliance_badge": "{group_dietary_rule}",
  "remote_logistics_alert": "Warnings on network dead-zones, ghat driving, early sunset, or stretches requiring packed backup veg food",
  "split_budget_per_person_inr": {{
    "transport": 1400,
    "food_and_dining": 900,
    "stays_or_entry_tickets": 1200,
    "emergency_buffer": 400,
    "total": 3900
  }},
  "timeline": [
    {{
      "time_slot": "07:30 AM - 08:15 AM",
      "day_label": "Day 1",
      "stop_type": "Breakfast Stop (Pure Veg Verified)",
      "place_name": "Exact Real Pure Veg Restaurant Name",
      "location_and_highway_cue": "Left side of Highway NH-48 heading towards Haveri/Sirsi, near landmark",
      "what_to_order_or_do": "Idli Vada, Masala Dosa, Filter Coffee",
      "estimated_cost_per_person_inr": 180,
      "backup_veg_option": "Second verified veg restaurant nearby",
      "google_maps_search_query": "Exact Restaurant Name City Karnataka India"
    }}
  ]
}}"""

class ModelGateway:
    # Ordered from fastest/lowest-congestion to reasoning models on your key
    CANDIDATE_MODELS = [
        "gemini-flash-latest",
        "gemini-flash-lite-latest",
        "gemini-3.5-flash-lite",
        "gemini-3.5-flash",
        "gemini-3.6-flash",
        "gemini-3.7-flash",
        "gemini-3.8-flash",
        "gemini-3.1-flash-lite"
    ]

    @staticmethod
    def _extract_json(raw_text: str):
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            raise

    @classmethod
    def generate_json(cls, prompt: str, room_code: str, task_type: str, prompt_version: str, tier: str = "reasoning", use_search_grounding: bool = False, api_key_override: Optional[str] = None):
        active_key = (api_key_override or GEMINI_API_KEY or "").strip()
        if not active_key:
            raise HTTPException(status_code=500, detail="GEMINI_API_KEY is missing in .env")

        # 25,000 ms (25s) per-request timeout so no single model can hang for 120s
        local_client = genai.Client(
            api_key=active_key,
            http_options=types.HttpOptions(timeout=25000)
        )
        last_error = None

        for model_name in cls.CANDIDATE_MODELS:
            start_t = time.time()
            try:
                config = types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.3,
                )
                response = local_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=config,
                )
                latency_ms = round((time.time() - start_t) * 1000, 2)
                raw_text = response.text or ""
                parsed_json = cls._extract_json(raw_text)
                est_tokens = (len(prompt) + len(raw_text)) // 4
                cls._log_telemetry(room_code, task_type, prompt_version, model_name, latency_ms, est_tokens, "SUCCESS")
                return parsed_json, model_name, latency_ms
            except Exception as e:
                err_str = str(e)
                last_error = err_str
                cls._log_telemetry(room_code, task_type, prompt_version, model_name, round((time.time() - start_t) * 1000, 2), 0, f"FALLBACK: {err_str[:60]}")
                continue

        raise HTTPException(status_code=502, detail=f"All gateway models busy/failed. Last error: {last_error}")

    @staticmethod
    def _log_telemetry(room_code: str, task_type: str, prompt_version: str, model_used: str, latency_ms: float, tokens: int, status: str):
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO telemetry (timestamp, room_code, task_type, prompt_version, model_used, latency_ms, estimated_tokens, status)
                    VALUES (:ts, :rc, :tt, :pv, :mu, :lat, :tok, :st)
                """),
                {"ts": time.time(), "rc": room_code, "tt": task_type, "pv": prompt_version, "mu": model_used, "lat": latency_ms, "tok": tokens, "st": status}
            )

class CreateTripRequest(BaseModel):
    room_code: str
    trip_name: str
    planning_mode: str = "fixed_destination"
    origin_city: str
    target_destination: str = ""
    trip_duration: str = "1-Day Micro-Trip (Hour-by-Hour)"
    must_visit_spots: str = ""

class PreferenceRequest(BaseModel):
    room_code: str
    user_name: str
    max_budget_inr: int
    preferred_dates: str
    dietary_pref: str = "Strict Pure Veg"
    vibe: str
    transport_pref: str
    dealbreakers: str = "None"

class GenerateRequest(BaseModel):
    room_code: str
    prompt_version: str = "v1_vibe_balanced"
    api_key_override: Optional[str] = None

class VoteRequest(BaseModel):
    room_code: str
    user_name: str
    ranked_choices: List[str]

class MicroItineraryRequest(BaseModel):
    room_code: str
    selected_option: Optional[str] = None
    api_key_override: Optional[str] = None

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.post("/trips/create")
def create_trip(req: CreateTripRequest):
    code = req.room_code.strip().upper()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM trips WHERE room_code = :c"), {"c": code})
        conn.execute(text("""
            INSERT INTO trips (room_code, trip_name, planning_mode, origin_city, target_destination, trip_duration, must_visit_spots, created_at, gen_count, last_gen_time)
            VALUES (:c, :tn, :pm, :oc, :td, :dur, :mv, :ca, 0, 0)
        """), {
            "c": code, "tn": req.trip_name.strip(), "pm": req.planning_mode,
            "oc": req.origin_city.strip(), "td": req.target_destination.strip(),
            "dur": req.trip_duration, "mv": req.must_visit_spots.strip(), "ca": time.time()
        })
    return {"status": "created", "room_code": code}

@app.post("/trips/preferences")
def submit_preference(req: PreferenceRequest):
    code = req.room_code.strip().upper()
    uname = req.user_name.strip()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM preferences WHERE room_code = :c AND user_name = :u"), {"c": code, "u": uname})
        conn.execute(text("""
            INSERT INTO preferences (room_code, user_name, max_budget_inr, preferred_dates, dietary_pref, vibe, transport_pref, dealbreakers)
            VALUES (:c, :u, :b, :d, :diet, :v, :t, :db)
        """), {
            "c": code, "u": uname, "b": req.max_budget_inr, "d": req.preferred_dates.strip(),
            "diet": req.dietary_pref, "v": req.vibe.strip(), "t": req.transport_pref, "db": req.dealbreakers.strip()
        })
    return {"status": "saved", "user_name": uname}

def _build_group_context(prefs: List[Dict]):
    strict_budget_cap = min(p["max_budget_inr"] for p in prefs)
    diets = [p["dietary_pref"] for p in prefs]
    if any("Pure Veg" in d or "Jain" in d for d in diets):
        group_dietary_rule = "100% STRICT PURE VEGETARIAN / JAIN REQUIRED: Every single meal stop MUST be a verified Pure Veg restaurant."
    elif any("Veg" in d for d in diets):
        group_dietary_rule = "VEGETARIAN FRIENDLY REQUIRED: All stops must have strong hygienic vegetarian meal options."
    else:
        group_dietary_rule = "Flexible diet (include authentic local cuisine and clean vegetarian options)."

    lines = [
        f"- {p['user_name']}: Max Budget INR {p['max_budget_inr']}, Diet: {p['dietary_pref']}, Dates: {p['preferred_dates']}, Vibe: {p['vibe']}, Transport: {p['transport_pref']}, Dealbreakers: {p['dealbreakers']}"
        for p in prefs
    ]
    return strict_budget_cap, group_dietary_rule, "\n".join(lines)

@app.post("/trips/generate")
def generate_proposals(req: GenerateRequest):
    code = req.room_code.strip().upper()
    with engine.begin() as conn:
        trip = conn.execute(text("SELECT * FROM trips WHERE room_code = :c"), {"c": code}).mappings().first()
        prefs = [dict(r) for r in conn.execute(text("SELECT * FROM preferences WHERE room_code = :c"), {"c": code}).mappings().all()]
        if not trip or not prefs:
            raise HTTPException(status_code=400, detail="Create a trip and add at least 1 friend preference first.")

    strict_budget_cap, group_dietary_rule, preferences_text = _build_group_context(prefs)
    template = PROMPT_REGISTRY.get(req.prompt_version, PROMPT_REGISTRY["v1_vibe_balanced"])
    prompt = template.format(
        planning_mode=trip["planning_mode"],
        origin_city=trip["origin_city"],
        target_destination=trip["target_destination"] or "Open Discovery",
        trip_duration=trip["trip_duration"],
        must_visit_spots=trip["must_visit_spots"] or "None specified",
        group_dietary_rule=group_dietary_rule,
        strict_budget_cap=strict_budget_cap,
        preferences_text=preferences_text
    )

    proposals, model_used, latency_ms = ModelGateway.generate_json(
        prompt=prompt, room_code=code, task_type="route_proposal_synthesis",
        prompt_version=req.prompt_version, api_key_override=req.api_key_override
    )

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM proposals WHERE room_code = :c"), {"c": code})
        conn.execute(text("""
            INSERT INTO proposals (room_code, prompt_version, model_used, proposals_json, latency_ms)
            VALUES (:c, :pv, :mu, :pj, :lat)
        """), {"c": code, "pv": req.prompt_version, "mu": model_used, "pj": json.dumps(proposals), "lat": latency_ms})
        conn.execute(text("DELETE FROM votes WHERE room_code = :c"), {"c": code})
        conn.execute(text("DELETE FROM micro_itineraries WHERE room_code = :c"), {"c": code})

    return {"prompt_version": req.prompt_version, "model_used": model_used, "latency_ms": latency_ms, "proposals": proposals}

@app.post("/trips/vote")
def submit_vote(req: VoteRequest):
    code = req.room_code.strip().upper()
    uname = req.user_name.strip()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM votes WHERE room_code = :c AND user_name = :u"), {"c": code, "u": uname})
        conn.execute(text("INSERT INTO votes (room_code, user_name, ranked_choices_json) VALUES (:c, :u, :rc)"),
                     {"c": code, "u": uname, "rc": json.dumps(req.ranked_choices)})
    return {"status": "vote_recorded", "user_name": uname}

@app.post("/trips/micro-itinerary")
def generate_micro_itinerary(req: MicroItineraryRequest):
    code = req.room_code.strip().upper()
    with engine.begin() as conn:
        trip = conn.execute(text("SELECT * FROM trips WHERE room_code = :c"), {"c": code}).mappings().first()
        prefs = [dict(r) for r in conn.execute(text("SELECT * FROM preferences WHERE room_code = :c"), {"c": code}).mappings().all()]
        votes = [dict(r) for r in conn.execute(text("SELECT * FROM votes WHERE room_code = :c"), {"c": code}).mappings().all()]
        prop_row = conn.execute(text("SELECT * FROM proposals WHERE room_code = :c"), {"c": code}).mappings().first()

    if not trip or not prefs:
        raise HTTPException(status_code=400, detail="Trip or participant preferences not found.")

    winning_option = req.selected_option
    if not winning_option and votes:
        consensus = compute_ranked_choice_winner(votes)
        if consensus:
            winning_option = consensus["winner"]
    if not winning_option and prop_row:
        props = json.loads(prop_row["proposals_json"])
        if props:
            winning_option = props[0].get("option_title")
    if not winning_option:
        winning_option = trip["target_destination"] or "Group Consensus Trip"

    strict_budget_cap, group_dietary_rule, preferences_text = _build_group_context(prefs)
    prompt = MICRO_ITINERARY_PROMPT.format(
        origin_city=trip["origin_city"], winning_option=winning_option,
        trip_duration=trip["trip_duration"], must_visit_spots=trip["must_visit_spots"] or "Top local spots",
        strict_budget_cap=strict_budget_cap, group_dietary_rule=group_dietary_rule,
        preferences_text=preferences_text
    )

    itinerary_data, model_used, latency_ms = ModelGateway.generate_json(
        prompt=prompt, room_code=code, task_type="highway_micro_itinerary",
        prompt_version="micro_v1", api_key_override=req.api_key_override
    )

    for item in itinerary_data.get("timeline", []):
        q = item.get("google_maps_search_query") or f"{item.get('place_name', '')} {winning_option}"
        item["google_maps_url"] = f"[https://www.google.com/maps/search/?api=1&query=](https://www.google.com/maps/search/?api=1&query=){urllib.parse.quote(q)}"

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM micro_itineraries WHERE room_code = :c"), {"c": code})
        conn.execute(text("""
            INSERT INTO micro_itineraries (room_code, winning_option, model_used, itinerary_json, latency_ms)
            VALUES (:c, :wo, :mu, :ij, :lat)
        """), {"c": code, "wo": winning_option, "mu": model_used, "ij": json.dumps(itinerary_data), "lat": latency_ms})

    return {"winning_option": winning_option, "model_used": model_used, "latency_ms": latency_ms, "itinerary": itinerary_data}

def compute_ranked_choice_winner(vote_rows: List[Dict]):
    ballots = [json.loads(v["ranked_choices_json"]) for v in vote_rows if v.get("ranked_choices_json")]
    if not ballots:
        return None

    borda_scores: Dict[str, int] = {}
    for ballot in ballots:
        n = len(ballot)
        for idx, choice in enumerate(ballot):
            borda_scores[choice] = borda_scores.get(choice, 0) + (n - idx)

    active_candidates = set(borda_scores.keys())
    rounds_history = []

    while active_candidates:
        first_choice_counts = {cand: 0 for cand in active_candidates}
        valid_ballots = 0
        for ballot in ballots:
            for choice in ballot:
                if choice in active_candidates:
                    first_choice_counts[choice] += 1
                    valid_ballots += 1
                    break
        rounds_history.append(first_choice_counts.copy())

        for cand, count in first_choice_counts.items():
            if valid_ballots > 0 and count > valid_ballots / 2:
                return {
                    "winner": cand,
                    "method": "Instant-Runoff Majority (>50%)",
                    "borda_scores": borda_scores,
                    "rounds": rounds_history,
                    "total_voters": len(ballots)
                }

        if len(active_candidates) <= 1:
            winner = next(iter(active_candidates))
            return {
                "winner": winner,
                "method": "Instant-Runoff Finalist (Borda Tie-Breaker)",
                "borda_scores": borda_scores,
                "rounds": rounds_history,
                "total_voters": len(ballots)
            }

        lowest_cand = min(active_candidates, key=lambda c: (first_choice_counts[c], borda_scores.get(c, 0)))
        active_candidates.remove(lowest_cand)

    return None

@app.get("/trips/{room_code}")
def get_trip_state(room_code: str):
    code = room_code.strip().upper()
    with engine.begin() as conn:
        trip = conn.execute(text("SELECT * FROM trips WHERE room_code = :c"), {"c": code}).mappings().first()
        if not trip:
            raise HTTPException(status_code=404, detail="Room code not found.")
        prefs = [dict(r) for r in conn.execute(text("SELECT * FROM preferences WHERE room_code = :c"), {"c": code}).mappings().all()]
        prop_row = conn.execute(text("SELECT * FROM proposals WHERE room_code = :c"), {"c": code}).mappings().first()
        votes = [dict(r) for r in conn.execute(text("SELECT * FROM votes WHERE room_code = :c"), {"c": code}).mappings().all()]
        itin_row = conn.execute(text("SELECT * FROM micro_itineraries WHERE room_code = :c"), {"c": code}).mappings().first()

    return {
        "trip": dict(trip),
        "preferences": prefs,
        "proposals_data": {
            "prompt_version": prop_row["prompt_version"],
            "model_used": prop_row["model_used"],
            "latency_ms": prop_row["latency_ms"],
            "proposals": json.loads(prop_row["proposals_json"])
        } if prop_row else None,
        "votes": votes,
        "consensus": compute_ranked_choice_winner(votes) if votes else None,
        "micro_itinerary_data": {
            "winning_option": itin_row["winning_option"],
            "model_used": itin_row["model_used"],
            "latency_ms": itin_row["latency_ms"],
            "itinerary": json.loads(itin_row["itinerary_json"])
        } if itin_row else None
    }

@app.get("/telemetry")
def get_telemetry():
    with engine.begin() as conn:
        rows = [dict(r) for r in conn.execute(text("SELECT * FROM telemetry ORDER BY id DESC LIMIT 50")).mappings().all()]
    return {"logs": rows}
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)