"""Rank stored news into a "top N market headlines" list.

RSS feeds carry no engagement/click data, so "top" is a transparent
heuristic rather than a popularity metric:

  - stories mentioning market-moving keywords (Fed, earnings, M&A, etc.)
    score higher
  - stories reported by *multiple* sources -- the same event covered by
    e.g. both CNBC and WSJ -- score higher, since cross-source pickup is a
    reasonable proxy for how big a story is
  - ties are broken by recency (most recent wins)

This is intentionally stdlib-only (difflib + re) so the project stays
framework-free -- no ML/NLP dependency required.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from difflib import SequenceMatcher

# Keyword -> weight. Broad, generic market-moving vocabulary rather than
# anything tied to a specific news cycle, so it doesn't need upkeep.
MARKET_KEYWORDS: dict[str, int] = {
    # monetary policy / macro
    "fed": 3, "federal reserve": 3, "interest rate": 3, "rate cut": 3, "rate hike": 3,
    "inflation": 3, "cpi": 3, "jobs report": 3, "unemployment": 2, "gdp": 3, "recession": 3,
    # broad market moves
    "s&p 500": 2, "dow jones": 2, "nasdaq": 2, "wall street": 1,
    "rally": 2, "plunge": 2, "crash": 3, "sell-off": 2, "selloff": 2, "surge": 2,
    "record high": 2, "volatility": 1, "bear market": 2, "bull market": 2,
    # corporate actions
    "earnings": 2, "merger": 2, "acquisition": 2, "ipo": 2, "bankruptcy": 3, "layoffs": 2,
    "guidance": 1, "buyback": 1, "stock split": 1,
    # geopolitics / energy / trade with market impact
    "tariff": 2, "trade war": 2, "sanctions": 2, "oil price": 2, "opec": 2,
    # regulatory
    "sec filing": 1, "investigation": 1, "lawsuit": 1, "antitrust": 2,
}

TITLE_SIMILARITY_THRESHOLD = 0.6


@dataclass
class TopStory:
    title: str
    link: str
    source: str
    published: str
    summary: str
    score: int
    other_sources: list[str] = field(default_factory=list)

    @property
    def num_sources(self) -> int:
        return 1 + len(self.other_sources)


def _normalize_title(title: str) -> str:
    text = title.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _cluster_by_title(rows: list[sqlite3.Row]) -> list[list[sqlite3.Row]]:
    """Group rows that are almost certainly reporting the same underlying story."""
    normalized = [_normalize_title(row["title"]) for row in rows]
    used = [False] * len(rows)
    clusters: list[list[sqlite3.Row]] = []

    for i, row in enumerate(rows):
        if used[i]:
            continue
        cluster = [row]
        used[i] = True
        for j in range(i + 1, len(rows)):
            if used[j]:
                continue
            if SequenceMatcher(None, normalized[i], normalized[j]).ratio() >= TITLE_SIMILARITY_THRESHOLD:
                cluster.append(rows[j])
                used[j] = True
        clusters.append(cluster)
    return clusters


def _keyword_score(text: str) -> int:
    lowered = text.lower()
    return sum(weight for keyword, weight in MARKET_KEYWORDS.items() if keyword in lowered)


def _score_cluster(cluster: list[sqlite3.Row]) -> int:
    combined_text = " ".join(f"{row['title']} {row['summary'] or ''}" for row in cluster)
    distinct_sources = {row["source"] for row in cluster}
    coverage_bonus = (len(distinct_sources) - 1) * 2  # extra outlets covering the same story
    return _keyword_score(combined_text) + coverage_bonus


def rank_top_stories(rows: list[sqlite3.Row], top_n: int = 5) -> list[TopStory]:
    """Rank a set of rows (typically one day's worth, see report.day_bounds_utc)
    and return the top N as TopStory objects, highest score first."""
    if not rows:
        return []

    clusters = _cluster_by_title(rows)
    scored = [(_score_cluster(cluster), cluster) for cluster in clusters]

    # Highest score first; ties broken by the most recent publish time in the cluster.
    scored.sort(key=lambda pair: (pair[0], max(r["published"] for r in pair[1])), reverse=True)

    top_stories: list[TopStory] = []
    for score, cluster in scored[:top_n]:
        representative = max(cluster, key=lambda r: r["published"])
        other_sources = sorted(
            {row["source"] for row in cluster if row["source"] != representative["source"]}
        )
        top_stories.append(
            TopStory(
                title=representative["title"],
                link=representative["link"],
                source=representative["source"],
                published=representative["published"],
                summary=representative["summary"] or "",
                score=score,
                other_sources=other_sources,
            )
        )
    return top_stories


def format_top_stories_markdown(stories: list[TopStory], heading: str = "Top Market Headlines") -> list[str]:
    """Render ranked stories as Markdown lines (no surrounding document structure)."""
    lines = [f"## {heading}", ""]
    if not stories:
        lines.append("_No stories to rank._")
        lines.append("")
        return lines

    for rank, story in enumerate(stories, start=1):
        lines.append(f"{rank}. **{story.title}** _(score: {story.score})_")
        source_line = f"   - Source: {story.source}"
        if story.other_sources:
            source_line += f" (also covered by: {', '.join(story.other_sources)})"
        lines.append(source_line)
        lines.append(f"   - Published: {story.published}")
        lines.append(f"   - Link: {story.link}")
        if story.summary:
            lines.append(f"   - Summary: {story.summary}")
        lines.append("")
    return lines
