# HackTheBruh backend

FastAPI service over Polymarket's public APIs (no auth required).

## Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # or requirements.txt for just the API
```

## Run the API

```bash
uvicorn app.main:app --reload
```

Interactive docs: http://127.0.0.1:8000/docs

| Endpoint | What it does |
|---|---|
| `GET /health` | Liveness of this API |
| `GET /polymarket/ping` | Reachability and latency of Gamma, CLOB and Data APIs |
| `GET /markets` | Markets from Gamma (`limit`, `offset`, `active`, `closed`, `order`, `ascending`) |
| `GET /markets/{slug}` | Single market by slug |
| `GET /trades` | Wallet-level trades (`condition_id`, `user`, `limit`, `cursor`) |

Upstream base URLs live in [app/config.py](app/config.py) and can be overridden with env vars
(`GAMMA_API_URL`, `CLOB_API_URL`, `DATA_API_URL`) or a `.env` file.

## Exploration

```bash
jupyter lab notebooks/exploration.ipynb
```

The notebook calls Polymarket directly, so the API does not need to be running.
