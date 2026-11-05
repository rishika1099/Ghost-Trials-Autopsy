"""Settings shared by the app, the agents and the snapshot builder. All come from env vars."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
# LiteLLM otherwise downloads a price list from GitHub on import. The bundled copy is enough.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

DATA_DIR = ROOT / "data"
DB_PATH = Path(os.environ.get("SNAPSHOT_DB", DATA_DIR / "autopsy.duckdb"))
MAPPINGS_PATH = DATA_DIR / "mappings.json"
PROMPTS_DIR = ROOT / "prompts"
CACHE_DIR = Path(os.environ.get("HTTP_CACHE_DIR", ROOT / ".cache" / "http"))

# LiteLLM routes these to Gemini on Vertex AI, with gcloud / Cloud Run service account credentials.
LEAD_MODEL = os.environ.get("LEAD_MODEL", "vertex_ai/gemini-3.5-flash")
RESEARCHER_MODEL = os.environ.get("RESEARCHER_MODEL", "vertex_ai/gemini-3.5-flash-lite")
WRITER_MODEL = os.environ.get("WRITER_MODEL", "vertex_ai/gemini-3.5-flash")
CHECKER_MODEL = os.environ.get("CHECKER_MODEL", "vertex_ai/gemini-3.5-flash")
VERTEX_LOCATION = os.environ.get("VERTEX_LOCATION", "global")
# The GCP project that pays for Gemini calls (the team uses Kshamaa's course credits).
# Empty means the project from `gcloud auth application-default login` (or the Cloud Run service's own project).
VERTEX_PROJECT = os.environ.get("VERTEX_PROJECT", "")
VERTEX_ARGS = {"vertex_location": VERTEX_LOCATION, **({"vertex_project": VERTEX_PROJECT} if VERTEX_PROJECT else {})}

# Caps. Prompts ask for restraint; code enforces it.
MAX_RESEARCH_ROUNDS = int(os.environ.get("MAX_RESEARCH_ROUNDS", 3))
RESEARCHER_MAX_TURNS = int(os.environ.get("RESEARCHER_MAX_TURNS", 8))
LEAD_MAX_TURNS = int(os.environ.get("LEAD_MAX_TURNS", 6))
WRITER_MAX_TURNS = int(os.environ.get("WRITER_MAX_TURNS", 4))
CHECKER_MAX_TURNS = int(os.environ.get("CHECKER_MAX_TURNS", 4))
REQUEST_BUDGET_S = float(os.environ.get("REQUEST_BUDGET_S", 240))
# Stop starting new rounds when less than this much of the budget is left: the Writer and Checker need it.
WRITE_RESERVE_S = float(os.environ.get("WRITE_RESERVE_S", 75))

# SEC asks every client to name itself with a contact email. Never hardcode a personal one.
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "")
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")
