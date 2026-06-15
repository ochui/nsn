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
LICENSEES_CSV_PATH = Path(__file__).parent / "All-List-of-Individual-Licensees_2.csv"
df = pd.read_csv(CSV_PATH)
licensees_df = pd.read_csv(LICENSEES_CSV_PATH, dtype=str, encoding="cp1252").fillna("")
licensees_df["__start_date"] = pd.to_datetime(
    licensees_df["START DATE"],
    dayfirst=True,
    errors="coerce",
)
licensees_df["__expiry_date"] = pd.to_datetime(
    licensees_df["EXPIRY DATE"],
    dayfirst=True,
    errors="coerce",
)
SEARCH_COLUMNS = [
    "Licensee",
    "Numbering Area",
    "Area Code",
    "National Destination Code (NDC)",
    "National (Significant) Number (N(S)N)",
]
LICENSEE_SEARCH_COLUMNS = ["COMPANY NAME", "ADDRESS", "CATEGORY"]
LICENSEE_DISPLAY_COLUMNS = [
    "COMPANY NAME",
    "CATEGORY",
    "ADDRESS",
    "START DATE",
    "EXPIRY DATE",
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


def normalize_text(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = re.sub(r"<[^>]+>", " ", str(value))
    return re.sub(r"\s+", " ", text).strip().lower()


def parse_date_param(value: str, label: str) -> tuple[pd.Timestamp | None, str]:
    value = value.strip()
    if not value:
        return None, ""

    parsed = pd.to_datetime(value, format="%Y-%m-%d", errors="coerce")
    if pd.isna(parsed):
        return None, f"{label} must use YYYY-MM-DD format."
    return parsed.normalize(), ""


def get_licensee_categories() -> list[str]:
    categories = licensees_df["CATEGORY"].dropna().astype(str).str.strip()
    return sorted(category for category in categories.unique() if category)


def licensee_text_score(query: str, row: pd.Series) -> tuple[int, float]:
    normalized_query = normalize_text(query)
    if not normalized_query:
        return 0, 0.0

    best_rank = 3
    best_score = 0.0
    for column in LICENSEE_SEARCH_COLUMNS:
        text = normalize_text(row.get(column, ""))
        if not text:
            continue

        if normalized_query == text:
            return 1, 100.0
        if text.startswith(normalized_query):
            best_rank = 1
            best_score = max(best_score, 99.0)
            continue
        if normalized_query in text:
            best_rank = 1
            best_score = max(best_score, 98.0)
            continue

        score = max(
            fuzz.partial_ratio(normalized_query, text),
            fuzz.token_set_ratio(normalized_query, text),
        )
        if score > best_score:
            best_rank = 2
            best_score = score

    if len(normalized_query) <= 3:
        threshold = 92
    elif len(normalized_query) <= 8:
        threshold = 84
    else:
        threshold = 75

    if best_score >= threshold:
        return best_rank, best_score
    return 0, 0.0


def licensee_record(row: pd.Series) -> dict[str, str]:
    return {column: search_value(row.get(column, "")) for column in LICENSEE_DISPLAY_COLUMNS}


def search_licensees(
    q: str = "",
    category: str = "",
    start_date: pd.Timestamp | None = None,
    end_date: pd.Timestamp | None = None,
    limit: int = 200,
) -> list[dict[str, str]]:
    has_filters = any([q.strip(), category.strip(), start_date is not None, end_date is not None])
    if not has_filters:
        return []

    normalized_category = normalize_text(category)
    results: list[tuple[int, str, dict[str, str]]] = []

    for _, row in licensees_df.iterrows():
        if normalized_category and normalize_text(row.get("CATEGORY", "")) != normalized_category:
            continue

        row_start = row["__start_date"]
        row_expiry = row["__expiry_date"]
        if start_date is not None and row_expiry < start_date:
            continue
        if end_date is not None and row_start > end_date:
            continue

        rank = 0
        if q.strip():
            rank, _ = licensee_text_score(q, row)
            if rank == 0:
                continue

        record = licensee_record(row)
        company_name = normalize_text(record["COMPANY NAME"])
        results.append((rank, company_name, record))

    results.sort(key=lambda item: (item[0], item[1]))
    return [record for _, _, record in results[:limit]]


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


@app.get("/licensees", response_class=HTMLResponse)
async def licensees(
    request: Request,
    q: str = "",
    category: str = "",
    start_date: str = "",
    end_date: str = "",
):
    results: list[dict[str, str]] = []
    errors: list[str] = []

    parsed_start_date, start_error = parse_date_param(start_date, "Start date")
    parsed_end_date, end_error = parse_date_param(end_date, "End date")
    errors.extend(error for error in [start_error, end_error] if error)

    if parsed_start_date is not None and parsed_end_date is not None and parsed_start_date > parsed_end_date:
        errors.append("Start date must be before or on end date.")

    if not errors:
        results = search_licensees(q, category, parsed_start_date, parsed_end_date)

    return templates.TemplateResponse(
        request,
        "licensees.html",
        {
            "results": results,
            "categories": get_licensee_categories(),
            "q": q,
            "category": category,
            "start_date": start_date,
            "end_date": end_date,
            "error": " ".join(errors),
        },
    )


if __name__ == "__main__":
    # Render expects apps to bind to 0.0.0.0 and use PORT from env.
    port = int(os.getenv("PORT", "10000"))
    uvicorn.run("nsn:app", host="0.0.0.0", port=port)
