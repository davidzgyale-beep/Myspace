"""Typer CLI: `edgar-export TICKER_OR_CIK --period annual --start-year 2020 --end-year 2025`."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer

from .cik_lookup import CIKLookup, InvalidCIKError, TickerNotFoundError
from .company_facts import get_company_facts_df
from .config import ConfigError, load_config
from .data_quality import (
    build_reconciliation_checks,
    combine_quality_reports,
    detect_anomalies,
    summarize_quality,
)
from .excel_writer import write_excel
from .fact_filter import FactFilterError, prepare_facts
from .sec_client import (
    SECClient,
    SECClientError,
    SECForbiddenError,
    SECNotFoundError,
    SECRateLimitError,
)
from .statement_builder import build_raw_facts_table, build_statement
from .statement_mappings import STATEMENT_MAPPINGS
from .utils import setup_logging

logger = logging.getLogger(__name__)

app = typer.Typer(add_completion=False, help="Export SEC EDGAR company financials to Excel.")


@app.command()
def export(
    ticker_or_cik: str = typer.Argument(
        ..., help="Ticker symbol (e.g. AAPL) or CIK (e.g. 0000320193 or 320193)."
    ),
    period: str = typer.Option("annual", "--period", help="'annual' or 'quarterly'."),
    start_year: Optional[int] = typer.Option(
        None, "--start-year", help="First fiscal year to include (default: end_year - 5)."
    ),
    end_year: Optional[int] = typer.Option(
        None, "--end-year", help="Last fiscal year to include (default: current year)."
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", help="Output .xlsx path (default: outputs/<TICKER>_<period>_<years>.xlsx)."
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Bypass the local response cache and force fresh requests."
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Fetch SEC EDGAR XBRL company facts and export a formatted Excel workbook."""
    setup_logging(verbose)

    period = period.lower().strip()
    if period not in ("annual", "quarterly"):
        typer.secho(f"Invalid --period '{period}': must be 'annual' or 'quarterly'.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    end_year = end_year or datetime.now().year
    start_year = start_year or (end_year - 5)
    if start_year > end_year:
        typer.secho("--start-year must be <= --end-year", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    try:
        config = load_config()
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1)

    client = SECClient(
        user_agent=config.user_agent,
        cache_dir=config.cache_dir,
        rate_limit=config.rate_limit,
        use_cache=not no_cache,
    )
    lookup = CIKLookup(client)

    try:
        cik10, ticker_title = lookup.resolve(ticker_or_cik)
    except (TickerNotFoundError, InvalidCIKError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1)

    typer.echo(f"Resolved '{ticker_or_cik}' -> CIK {cik10}")

    try:
        facts_df, company_meta = get_company_facts_df(client, cik10)
    except SECNotFoundError as exc:
        typer.secho(f"Company facts not found: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    except SECForbiddenError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1)
    except SECRateLimitError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1)
    except SECClientError as exc:
        typer.secho(f"SEC EDGAR request failed: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    if facts_df.empty:
        typer.secho("No XBRL company facts were returned for this company.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)

    try:
        prepared_df = prepare_facts(facts_df, period, start_year, end_year)
    except FactFilterError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1)

    if prepared_df.empty:
        typer.secho(
            f"Warning: no {period} facts found between {start_year} and {end_year} "
            "for this company. The workbook will still be generated but sheets will "
            "have no period columns.",
            fg=typer.colors.YELLOW,
        )

    statements = {}
    quality_by_statement = {}
    for statement_name, mapping in STATEMENT_MAPPINGS.items():
        wide_df, statement_quality_df = build_statement(prepared_df, mapping)
        statements[statement_name] = wide_df
        quality_by_statement[statement_name] = statement_quality_df

    raw_facts_df = build_raw_facts_table(prepared_df)
    combined_quality = combine_quality_reports(quality_by_statement)
    quality_summary = summarize_quality(combined_quality)
    reconciliation_df = build_reconciliation_checks(statements)
    anomalies_df = detect_anomalies(statements)

    company_name = company_meta.get("entity_name") or ticker_title or ticker_or_cik

    metadata = {
        "Company Name": company_name,
        "Ticker/Input": ticker_or_cik,
        "CIK": cik10,
        "Period Type": period,
        "Start Year": start_year,
        "End Year": end_year,
        "Generated At (UTC)": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "Data Source": "SEC EDGAR data.sec.gov XBRL Company Facts API",
    }

    if output is None:
        safe_name = ticker_or_cik.strip().upper().replace("/", "-")
        output = Path("outputs") / f"{safe_name}_{period}_{start_year}_{end_year}.xlsx"

    write_excel(
        output_path=output,
        statements=statements,
        raw_facts_df=raw_facts_df,
        quality_df=combined_quality,
        quality_summary_df=quality_summary,
        metadata=metadata,
        quality_by_statement=quality_by_statement,
        reconciliation_df=reconciliation_df,
        anomalies_df=anomalies_df,
    )

    typer.secho(f"Excel workbook written to {output}", fg=typer.colors.GREEN)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
