"""Shared data shapes passed between the fetcher and the database layer."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NewsItem:
    title: str
    link: str
    published: str  # ISO-8601 UTC timestamp
    source: str
    summary: str
