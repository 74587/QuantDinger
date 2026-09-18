"""Independent, source-labelled company research capabilities.

Each capability can fail or fall back without discarding another capability's
evidence. Retrieval time is never represented as a filing or settlement date.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import requests

from app.data_providers import get_cached, set_cached
from app.data_providers import us_research as us


DOMAINS = frozenset({
    "company_profile", "filings", "fundamentals", "ownership", "insider_activity",
    "analyst_expectations", "options", "short_interest", "competitors", "web_research",
})
REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax",
)


def _meta(source: str, url: str, scope: str, as_of: str | None = None) -> dict:
    return {"source": source, "source_url": url, "scope": scope,
            "as_of": as_of, "retrieved_at": us._utc_now()}


def _nasdaq(symbol: str, domain: str, timeout: float, http_get=requests.get) -> dict:
    paths = {
        "company_profile": f"company/{symbol}/company-profile",
        "analyst_expectations": f"analyst/{symbol}/targetprice",
        "insider_activity": f"company/{symbol}/insider-trades",
        "short_interest": f"quote/{symbol}/short-interest",
        "filings": f"company/{symbol}/sec-filings",
    }
    response = http_get(
        f"https://api.nasdaq.com/api/{paths[domain]}",
        params={"limit": 12, "assetclass": "stocks"},
        headers={"User-Agent": us._BROWSER_USER_AGENT, "Accept": "application/json",
                 "Origin": "https://www.nasdaq.com"}, timeout=timeout,
    )
    response.raise_for_status()
    data = response.json().get("data") or {}
    page = {"company_profile": "company-profile", "analyst_expectations": "analyst-research",
            "insider_activity": "insider-activity", "short_interest": "short-interest",
            "filings": "sec-filings"}[domain]
    url = f"https://www.nasdaq.com/market-activity/stocks/{symbol.lower()}/{page}"
    meta = _meta("nasdaq", url, "provider_snapshot")
    if domain == "company_profile":
        profile = {k: (data.get(v) or {}).get("value") for k, v in {
            "name": "CompanyName", "description": "CompanyDescription", "industry": "Industry",
            "sector": "Sector", "website": "CompanyUrl",
        }.items()}
        return {**meta, **profile} if profile.get("name") else {}
    if domain == "analyst_expectations":
        overview = data.get("consensusOverview") or {}
        value = us._number(overview.get("priceTarget"))
        if value is None:
            return {}
        return {**meta, "consensus_target_usd": value,
                "target_low_usd": us._number(overview.get("lowPriceTarget")),
                "target_high_usd": us._number(overview.get("highPriceTarget")),
                "ratings": {key: us._number(overview.get(key)) for key in ("buy", "hold", "sell")},
                "scope": "provider_analyst_consensus_not_guaranteed_price"}
    if domain == "filings":
        rows = [{"form": row.get("formType"), "filing_date": us._iso_date(row.get("filed")),
                 "report_date": us._iso_date(row.get("period")),
                 "url": (row.get("view") or {}).get("htmlLink")}
                for row in data.get("rows") or []]
        return {**meta, "filings": rows[:12], "scope": "provider_recent_filing_index"} if rows else {}
    if domain == "insider_activity":
        rows = ((data.get("transactionTable") or {}).get("table") or {}).get("rows") or []
        trades = [{"name": row.get("insider"), "role": row.get("relation"),
                   "date": us._iso_date(row.get("lastDate")), "transaction": row.get("transactionType"),
                   "ownership_type": row.get("ownType"), "shares": us._number(row.get("sharesTraded")),
                   "price_usd": us._number(row.get("lastPrice"))} for row in rows[:12]]
        return {**meta, "transactions": trades, "scope": "reported_transactions_not_all_open_market_trades"} if trades else {}
    rows = (data.get("shortInterestTable") or {}).get("rows") or []
    if not rows:
        return {}
    row = rows[0]
    return {**meta, "as_of": us._iso_date(row.get("settlementDate")),
            "shares_short": us._number(row.get("interest")),
            "days_to_cover": us._number(row.get("daysToCover")),
            "average_daily_volume": us._number(row.get("avgDailyShareVolume")),
            "scope": "reported_short_interest_not_short_volume",
            "missing_fields": ["short_percent_of_float_pct"]}


def normalize_annual_revenue(payload: dict, cik: str, years: int = 5) -> dict:
    """Select consolidated full-year revenue, keeping restatements and units explicit."""
    facts = (payload.get("facts") or {}).get("us-gaap") or {}
    by_period: dict[tuple[str, str], dict] = {}
    for priority, tag in enumerate(REVENUE_TAGS):
        for unit, rows in (facts.get(tag, {}).get("units") or {}).items():
            if unit != "USD":
                continue
            for row in rows:
                if row.get("form") not in {"10-K", "10-K/A", "20-F", "20-F/A"}:
                    continue
                try:
                    start, end = date.fromisoformat(row["start"]), date.fromisoformat(row["end"])
                    if not 330 <= (end - start).days <= 380:
                        continue
                except (KeyError, TypeError, ValueError):
                    continue
                value = us._number(row.get("val"))
                if value is None or value < 0:
                    continue
                point = {"period_start": start.isoformat(), "period_end": end.isoformat(),
                         "value": value, "unit": unit, "filed": row.get("filed"),
                         "accession": row.get("accn"), "concept": tag, "priority": priority}
                key = (end.isoformat(), unit)
                old = by_period.get(key)
                if old is None or (str(point["filed"] or ""), -priority) > (str(old["filed"] or ""), -old["priority"]):
                    by_period[key] = point
    points = sorted(by_period.values(), key=lambda point: point["period_end"])[-years:]
    if not points:
        return {}
    for point in points:
        point.pop("priority", None)
        acc = str(point.get("accession") or "").replace("-", "")
        point["source_url"] = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/"
    return {**_meta("sec_edgar", f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                    "annual_consolidated_revenue_latest_reported_comparatives", points[-1]["period_end"]),
            "metric": "revenue", "unit": "USD", "period_type": "annual",
            "requested_years": years, "points": points,
            "complete": len(points) >= years}


def _sec(symbol: str, domain: str, years: int, timeout: float, http_get=requests.get) -> dict:
    if domain == "filings":
        result = us.fetch_sec_research(symbol, http_get=http_get, timeout=timeout)
        rows = result.get("sec_filings") or []
        cik = (result.get("identity") or {}).get("cik")
        return {**_meta("sec_edgar", f"https://www.sec.gov/edgar/browse/?CIK={cik}",
                        "recent_filing_index", rows[0].get("filing_date") if rows else None),
                "filings": rows, "identity": result.get("identity")} if rows else {}
    company = us._sec_ticker_map(http_get=http_get, timeout=timeout).get(symbol)
    if not company:
        return {}
    cik = f"{int(company['cik']):010d}"
    payload = us._request_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                               http_get=http_get, timeout=timeout)
    return normalize_annual_revenue(payload, cik, years)


def company_documents(symbol: str, *, timeout: float = 8, http_get=requests.get) -> dict:
    """Discover latest primary annual, quarterly and proxy documents for any SEC issuer."""
    company = us._sec_ticker_map(http_get=http_get, timeout=timeout).get(us._symbol(symbol))
    if not company:
        return {}
    cik = f"{int(company['cik']):010d}"
    payload = us._request_json(f"https://data.sec.gov/submissions/CIK{cik}.json",
                              http_get=http_get, timeout=timeout)
    recent = ((payload.get("filings") or {}).get("recent") or {})
    documents, seen = [], set()
    for index, form in enumerate(recent.get("form") or []):
        if form not in {"10-K", "20-F", "10-Q", "DEF 14A"} or form in seen:
            continue
        acc = str(us._at(recent.get("accessionNumber"), index) or "").replace("-", "")
        filename = us._at(recent.get("primaryDocument"), index)
        if not acc or not filename:
            continue
        seen.add(form)
        documents.append({"form": form, "filed": us._at(recent.get("filingDate"), index),
                          "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{filename}"})
    return {"data": {"documents": documents, "issuer": payload.get("name"),
                      **_meta("sec_edgar", f"https://data.sec.gov/submissions/CIK{cik}.json",
                              "document_index_not_document_contents")}} if documents else {}


def _yahoo(symbol: str, domain: str, years: int = 5, yf_client=None) -> dict:
    if yf_client is None:
        import yfinance as yf_client
        us._configure_yfinance_cache(yf_client)
    ticker = yf_client.Ticker(symbol)
    base_url = f"https://finance.yahoo.com/quote/{symbol}"
    meta = _meta("yahoo_finance", base_url, "provider_snapshot")
    if domain == "fundamentals":
        frame = ticker.income_stmt
        if frame is None or frame.empty or "Total Revenue" not in frame.index:
            return {}
        points = [{"period_end": str(column.date()), "value": us._number(value), "unit": "USD"}
                  for column, value in frame.loc["Total Revenue"].items() if us._number(value) is not None]
        info = ticker.info or {}
        unit = info.get("financialCurrency")
        if not unit:
            return {}
        points = sorted(points, key=lambda row: row["period_end"])[-years:]
        for point in points:
            point["unit"] = unit
        return {**meta, "metric": "revenue", "unit": unit, "period_type": "annual", "points": points,
                "requested_years": years, "complete": len(points) >= years}
    if domain == "insider_activity":
        frame = ticker.insider_transactions
        if frame is None or frame.empty:
            return {}
        trades = [{"name": row.get("Insider"), "date": str(row.get("Start Date") or ""),
                   "transaction": row.get("Text"), "shares": us._number(row.get("Shares")),
                   "value": us._number(row.get("Value"))} for _, row in frame.head(12).iterrows()]
        return {**meta, "transactions": trades, "scope": "provider_reported_insider_transactions"}
    info = ticker.info or {}
    if domain == "company_profile":
        officers = [{"name": officer.get("name"), "title": officer.get("title")}
                    for officer in info.get("companyOfficers") or []]
        return {**meta, "name": info.get("longName"), "description": info.get("longBusinessSummary"),
                "website": info.get("website"), "industry": info.get("industry"),
                "sector": info.get("sector"), "officers": officers} if info.get("longName") else {}
    if domain == "analyst_expectations":
        target = us._number(info.get("targetMeanPrice"))
        return {**meta, "consensus_target": target, "currency": info.get("currency"),
                "target_low": us._number(info.get("targetLowPrice")),
                "target_high": us._number(info.get("targetHighPrice")),
                "analyst_count": us._number(info.get("numberOfAnalystOpinions"))} if target is not None else {}
    if domain == "short_interest":
        value = us._number(info.get("shortPercentOfFloat"))
        shares = us._number(info.get("sharesShort"))
        return {**meta, "short_percent_of_float_pct": value * 100 if value is not None else None,
                "shares_short": shares, "days_to_cover": us._number(info.get("shortRatio")),
                "as_of": us._timestamp(info.get("dateShortInterest")),
                "scope": "reported_short_interest_not_short_volume"} if shares is not None else {}
    if domain == "options":
        expiries = list(ticker.options or [])
        if not expiries:
            return {}
        expiry = expiries[0]
        chain = ticker.option_chain(expiry)
        spot = us._number(info.get("currentPrice") or info.get("regularMarketPrice"))
        iv = us._nearest_atm_iv(chain.calls, chain.puts, spot)
        return {**meta, "expiry": expiry, "spot": spot, "nearest_atm_implied_volatility_pct": iv,
                "scope": "nearest_expiry_nearest_available_strike_iv_not_30d_iv_or_iv_rank"} if iv is not None else {}
    return {}


def lookup_company(symbol: str, domain: str, *, years: int = 5, timeout: float = 8) -> dict[str, Any]:
    """Fetch one capability and retain explicit per-provider outcomes."""
    symbol = us._symbol(symbol)
    years = min(10, max(1, int(years)))
    if domain not in DOMAINS:
        raise ValueError("Unsupported research domain")
    key = f"company_capability:v1:{symbol}:{domain}:{years}"
    cached = get_cached(key, 900)
    if isinstance(cached, dict):
        return cached
    if domain == "ownership":
        raw = us.collect_us_ownership(symbol, timeout=timeout)
        return {"data": raw.get("ownership") or {}, "provider_status": raw.get("_provider_status") or {}}
    chains = {
        "company_profile": ("yahoo", "nasdaq"),
        "filings": ("sec", "nasdaq"),
        "fundamentals": ("sec", "yahoo"),
        "insider_activity": ("nasdaq", "yahoo"),
        "analyst_expectations": ("nasdaq", "yahoo"),
        "options": ("yahoo",),
        "short_interest": ("yahoo", "nasdaq"),
    }
    attempts = []
    data = {}
    for provider in chains.get(domain, ()):
        try:
            if provider == "sec":
                data = _sec(symbol, domain, years, timeout)
            elif provider == "nasdaq":
                data = _nasdaq(symbol, domain, timeout)
            else:
                data = _yahoo(symbol, domain, years)
            attempts.append({"provider": provider, "status": "success" if data else "empty"})
            if data:
                break
        except Exception as exc:
            attempts.append({"provider": provider, "status": "error", "error_type": type(exc).__name__})
    result = {"data": data, "provider_status": {"attempts": attempts}}
    if data:
        set_cached(key, result, 900)
    return result
