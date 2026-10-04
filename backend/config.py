import os


class Config:
    # postgresql://user:pass@host:5432/rasad  (PostGIS)  or  sqlite:///rasad.db  (local dev, no PostGIS)
    DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///rasad.db")
    API_KEY = os.environ.get("RASAD_API_KEY", "")            # required on writes when set

    # Qwen3-8B on any OpenAI-compatible server (vLLM, Ollama)
    QWEN_BASE_URL = os.environ.get("QWEN_BASE_URL", "")      # e.g. http://localhost:8000/v1
    QWEN_MODEL = os.environ.get("QWEN_MODEL", "Qwen/Qwen3-8B")
    QWEN_API_KEY = os.environ.get("QWEN_API_KEY", "EMPTY")
    QWEN_TIMEOUT = float(os.environ.get("QWEN_TIMEOUT", "60"))

    # Meta-heuristic engine
    GA_POP = int(os.environ.get("RASAD_GA_POP", "50"))
    GA_GENS = int(os.environ.get("RASAD_GA_GENS", "80"))
    ACO_ANTS = int(os.environ.get("RASAD_ACO_ANTS", "12"))
    ACO_ITERS = int(os.environ.get("RASAD_ACO_ITERS", "15"))

    # Helicopter payload falls with altitude (thinner air). Planning assumption, not an aircraft rating:
    # full payload up to DERATE_FROM_M, then it loses DERATE_PER_KM of the rated payload per 1,000 m, never below FLOOR.
    HELI_DERATE_FROM_M = float(os.environ.get("RASAD_HELI_DERATE_FROM_M", "3000"))
    HELI_DERATE_PER_KM = float(os.environ.get("RASAD_HELI_DERATE_PER_KM", "0.18"))
    HELI_DERATE_FLOOR = float(os.environ.get("RASAD_HELI_DERATE_FLOOR", "0.30"))
