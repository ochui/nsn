import os
import re
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from rapidfuzz import fuzz
import uvicorn

app = FastAPI(title="Nigerian NSN Lookup")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

CSV_PATH = Path(__file__).parent / "national_numbering_plan.csv"
df = pd.read_csv(CSV_PATH)
SEARCH_COLUMNS = [
    "Licensee",
    "Numbering Area",
    "Area Code",
    "National Destination Code (NDC)",
    "National (Significant) Number (N(S)N)",
]


def normalize_number(number: str) -> str:
    digits = re.sub(r"\D", "", number)
    if digits.startswith("234") and len(digits) > 10:
        digits = digits[3:]
    if digits.startswith("0"):
        digits = digits[1:]
    return digits


def normalize_block(block: Any) -> str:
    if pd.isna(block):
        return ""
    return re.sub(r"[XY].*$", "", str(block)).strip()


def get_query_threshold(query: str) -> int:
    length = len(query.strip())
    if length <= 3:
        return 95
    if length <= 6:
        return 88
    if length <= 10:
        return 82
    return 75


def is_numeric_query(query: str) -> bool:
    return bool(re.fullmatch(r"[+\d\s()-]+", query.strip()))


def is_phone_query(query: str) -> bool:
    return is_numeric_query(query) and len(normalize_number(query)) >= 7


def search_value(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def search(query: str, limit: int = 100) -> list[dict[Any, Any]]:
    query = query.strip()
    if not query:
        return []

    results: list[tuple[int, float, dict[Any, Any]]] = []
    seen: set[Any] = set()
    lowered_query = query.lower()

    phone_query = is_phone_query(query)
    if phone_query:
        nsn = normalize_number(query)
        for _, row in df.iterrows():
            block = normalize_block(row["National (Significant) Number (N(S)N)"])
            block_digits = re.sub(r"\D", "", block)
            if nsn and block_digits and nsn.startswith(block_digits):
                record = row.to_dict()
                key = record.get("S/N", tuple(record.items()))
                if key not in seen:
                    seen.add(key)
                    results.append((0, -len(block_digits), record))

    if phone_query:
        results.sort(key=lambda item: (item[0], item[1]))
        return [record for _, _, record in results[:limit]]

    threshold = get_query_threshold(query)
    for _, row in df.iterrows():
        record = row.to_dict()
        key = record.get("S/N", tuple(record.items()))
        if key in seen:
            continue

        best_score = 0.0
        rank = 4
        for column in SEARCH_COLUMNS:
            text = search_value(record.get(column, ""))
            if not text:
                continue

            text_lower = text.lower()
            if lowered_query == text_lower:
                best_score = 100.0
                rank = 1
                break
            if text_lower.startswith(lowered_query):
                best_score = max(best_score, 99.0)
                rank = min(rank, 1)
                continue
            if any(token.startswith(lowered_query) for token in re.findall(r"\w+", text_lower)):
                best_score = max(best_score, 98.0)
                rank = min(rank, 2)
                continue
            if lowered_query in text_lower:
                best_score = max(best_score, 97.0)
                rank = min(rank, 2)
                continue

            score = fuzz.partial_ratio(lowered_query, text_lower)
            if score > best_score:
                best_score = score
                rank = 3

        if best_score >= threshold:
            seen.add(key)
            results.append((rank, -best_score, record))

    results.sort(key=lambda item: (item[0], item[1]))
    return [record for _, _, record in results[:limit]]


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    q: str = "",
):
    results: list[dict[Any, Any]] = []
    error = ""

    if q:
        results = search(q)
        if not results:
            error = f"No results found for '{q}'."

    return templates.TemplateResponse(
        request,
        "index.html",
        {"results": results, "error": error, "q": q},
    )


if __name__ == "__main__":
    # Render expects apps to bind to 0.0.0.0 and use PORT from env.
    port = int(os.getenv("PORT", "10000"))
    uvicorn.run("nsn:app", host="0.0.0.0", port=port)
