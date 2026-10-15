# QuantTrading - Copilot Instructions

## Project Overview
QuantTrading is a quantitative trading visualization system built on OKX exchange API, with AI evolution modules from vigilant-couscous.

## Tech Stack
- Backend: Python 3.12, FastAPI, uvicorn
- Frontend: HTML/CSS/JS, Chart.js
- Database: SQLite (memory/nexus/)
- AI: crewai, AGI brain, evolution modules
- Testing: pytest, pytest-cov, flake8
- CI/CD: GitHub Actions

## Code Style
- Follow PEP 8, max line length 120
- Use type hints on all function signatures
- Use f-strings for string formatting
- Use dataclasses for data structures
- Use async/await for API endpoints

## Project Structure
- `backend/api/` - FastAPI routes
- `backend/core/` - Core services (OKX data, trade, auth, resilience)
- `backend/indicators/` - 508 technical indicators (pandas-ta)
- `vigilant-couscous/` - AI evolution modules (AGI, agents, evolution, strategy, data, memory)
- `frontend/` - Single-page HTML app
- `scripts/` - Utility scripts
- `tests/` - Unit tests

## Key Conventions
- API responses: {'code': 0, 'data': ...}
- Environment variables in .env, loaded via python-dotenv
- crewai is optional dependency, use lazy imports
- OKX API uses simulated mode by default (OKX_SIMULATED=1)
- All sensitive data in .env, never hardcoded

## Testing
- Run: `python -m pytest tests/ -v -o addopts=''`
- Coverage: `python -m pytest tests/ --cov=.`
- Lint: `flake8 backend/ --max-line-length=120`
- Merge check: `python scripts/post_merge_check.py`
