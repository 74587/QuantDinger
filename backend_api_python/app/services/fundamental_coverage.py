"""Field-level coverage at a user-selected observation date."""
import math
from datetime import date

from app.services.fundamental_data import FUNDAMENTAL_FIELDS, get_fundamental_data_service
from app.services.fundamental_sync import fields_for, members_for, query


def member_coverage(members, fields, as_of, source=None):
    get_fundamental_data_service().ensure_schema()
    fields = fields_for(fields)
    as_of = date.fromisoformat(str(as_of)[:10])
    rows = query('''SELECT DISTINCT ON (market,symbol) * FROM qd_fundamental_snapshots
        WHERE symbol=ANY(%s) AND available_at<=%s AND (%s IS NULL OR source=%s)
        ORDER BY market,symbol,available_at DESC,period_end DESC,ingested_at DESC''',
        ([item['symbol'] for item in members], as_of, source, source), True)
    found = {(r['market'], r['symbol']): r for r in rows}
    result = []
    for member in members:
        row = found.get((member['market'], member['symbol'])) or {}
        missing = []
        for field in fields:
            value = row.get(field)
            valid = isinstance(value, (float, int)) and math.isfinite(value)
            if field in {'market_cap', 'shares_outstanding'}:
                valid = valid and value > 0
            if not valid:
                missing.append(field)
        stale = bool(row and (as_of - row['period_end']).days > 200)
        result.append(dict(market=member['market'], symbol=member['symbol'], missing=missing, stale=stale,
            available_at=row.get('available_at'), period_end=row.get('period_end'), source=row.get('source'),
            ingested_at=row.get('ingested_at'), ready=not missing and not stale))
    return result


def coverage_for(user_id, universe_id, fields=None, as_of=None):
    fields = fields_for(fields)
    members = members_for(user_id, universe_id)
    rows = member_coverage(members, fields, as_of or date.today())
    return dict(as_of=str(as_of or date.today()), fields=fields, available_fields=list(FUNDAMENTAL_FIELDS),
        total=len(rows), ready=sum(item['ready'] for item in rows), items=rows)
