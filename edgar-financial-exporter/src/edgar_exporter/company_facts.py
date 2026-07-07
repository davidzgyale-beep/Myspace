"""Fetch and parse SEC's XBRL "company facts" API into a unified DataFrame."""

from __future__ import annotations

from typing import Tuple

import pandas as pd

from .sec_client import SECClient

COMPANY_FACTS_URL_TEMPLATE = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"

RAW_FACT_COLUMNS = [
    "taxonomy",
    "tag",
    "label",
    "description",
    "unit",
    "value",
    "fiscal_year",
    "fiscal_period",
    "form",
    "filed",
    "frame",
    "accession_number",
    "start",
    "end",
]


def fetch_company_facts(client: SECClient, cik10: str) -> dict:
    """Fetch the raw companyfacts JSON payload for a 10-digit, zero-padded CIK."""
    url = COMPANY_FACTS_URL_TEMPLATE.format(cik10=cik10)
    return client.get_json(url)


def parse_company_facts(raw: dict) -> pd.DataFrame:
    """Flatten the nested companyfacts JSON into one row per reported fact/period/unit."""
    rows = []
    facts = raw.get("facts", {}) or {}
    for taxonomy, tags in facts.items():
        for tag, tag_data in tags.items():
            label = tag_data.get("label")
            description = tag_data.get("description")
            units = tag_data.get("units", {}) or {}
            for unit, entries in units.items():
                for entry in entries:
                    rows.append(
                        {
                            "taxonomy": taxonomy,
                            "tag": tag,
                            "label": label,
                            "description": description,
                            "unit": unit,
                            "value": entry.get("val"),
                            "fiscal_year": entry.get("fy"),
                            "fiscal_period": entry.get("fp"),
                            "form": entry.get("form"),
                            "filed": entry.get("filed"),
                            "frame": entry.get("frame"),
                            "accession_number": entry.get("accn"),
                            "start": entry.get("start"),
                            "end": entry.get("end"),
                        }
                    )

    if not rows:
        return pd.DataFrame(columns=RAW_FACT_COLUMNS)

    return pd.DataFrame(rows, columns=RAW_FACT_COLUMNS)


def get_company_facts_df(client: SECClient, cik10: str) -> Tuple[pd.DataFrame, dict]:
    """Fetch + parse company facts, returning (facts_dataframe, company_metadata)."""
    raw = fetch_company_facts(client, cik10)
    df = parse_company_facts(raw)
    meta = {
        "cik": raw.get("cik"),
        "entity_name": raw.get("entityName"),
    }
    return df, meta
