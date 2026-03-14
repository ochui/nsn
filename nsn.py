import re
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Nigerian NSN Lookup")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

CSV_PATH = Path(__file__).parent / "national_numbering_plan.csv"
df = pd.read_csv(CSV_PATH)


def normalize_number(number: str) -> str:
    number = number.strip()
    if number.startswith("0"):
        number = number[1:]
    return number


def search_by_number(number: str) -> list[dict]:
    nsn = normalize_number(number)
    matched = df[df["National (Significant) Number (N(S)N)"].apply(
        lambda x: isinstance(x, str) and nsn.startswith(x.replace("X", ""))
    )]
    return matched.to_dict(orient="records")


def search_by_area(area: str) -> list[dict]:
    area = area.strip().lower()
    matched = df[df["Numbering Area"].str.lower().str.contains(re.escape(area))]
    return matched.to_dict(orient="records")


def search_by_operator(operator: str) -> list[dict]:
    operator = operator.strip().lower()
    matched = df[df["Licensee"].str.lower().str.contains(re.escape(operator))]
    return matched.to_dict(orient="records")


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    mode: str = Query(default=""),
    q: str = Query(default=""),
):
    results = []
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
