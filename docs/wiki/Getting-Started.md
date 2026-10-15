# Getting Started

## Prerequisites
- Python 3.12+
- Node.js 20+
- Git 2.40+

## Installation
```bash
git clone https://github.com/you200109/quanttrading.git
cd quanttrading
pip install -r requirements.txt
```

## Start Backend
```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

## Access Frontend
Open http://localhost:8000 in your browser.

## Run Tests
```bash
python -m pytest tests/ -v
```

## Codespaces
Repository page > Code > Codespaces > Create codespace on main