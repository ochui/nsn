# Nigerian NSN Lookup

Simple FastAPI web app for searching Nigeria's national numbering plan by number, area, or operator.

## Run locally

```bash
uv run uvicorn nsn:app --host 0.0.0.0 --port 8000
```

Open `http://127.0.0.1:8000`.

## Deploy on Render

Use this start command:

```bash
uv run python nsn.py
```

`nsn.py` reads `PORT` from the environment (default `10000`) and binds to `0.0.0.0`.
