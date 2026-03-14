import os
import re
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import uvicorn

app = FastAPI(title="Nigerian NSN Lookup")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

CSV_PATH = Path(__file__).parent / "national_numbering_plan.csv"
df = pd.read_csv(CSV_PATH)


def normalize_number(number: str) -> str:
    number = number.strip()
    if number.startswith("0"):
        number = number[1:]
    return number


def search_by_number(number: str) -> list[dict[Any, Any]]:
    nsn = normalize_number(number)
    blocks = df["National (Significant) Number (N(S)N)"].tolist()
    mask = [isinstance(block, str) and nsn.startswith(block.replace("X", "")) for block in blocks]
    matched = df[mask]
    return matched.to_dict(orient="records")


def search_by_area(area: str) -> list[dict[Any, Any]]:
    area = area.strip().lower()
    matched = df[df["Numbering Area"].str.lower().str.contains(re.escape(area))]
    return matched.to_dict(orient="records")


def search_by_operator(operator: str) -> list[dict[Any, Any]]:
    operator = operator.strip().lower()
    matched = df[df["Licensee"].str.lower().str.contains(re.escape(operator))]
    return matched.to_dict(orient="records")


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    mode: str = Query(default=""),
    q: str = Query(default=""),
):
    results: list[dict[Any, Any]] = []
    error = ""

    if mode and q:
        if mode == "number":
            results = search_by_number(q)
        elif mode == "area":
            results = search_by_area(q)
        elif mode == "operator":
            results = search_by_operator(q)
        else:
            error = "Invalid search mode."

        if not results and not error:
            error = f"No results found for '{q}'."

    return templates.TemplateResponse(
        "index.html",
        {"request": request, "results": results, "error": error, "mode": mode, "q": q},
    )


if __name__ == "__main__":
    # Render expects apps to bind to 0.0.0.0 and use PORT from env.
    port = int(os.getenv("PORT", "10000"))
    uvicorn.run("nsn:app", host="0.0.0.0", port=port)
