"""
K-line (OHLCV) API routes.
"""
from flask import jsonify, request
from app.openapi.blueprint import HumanBlueprint as Blueprint
from datetime import datetime
import traceback

from app.services.kline import KlineService
from app.utils.logger import get_logger
from app.services.market.watchlist import validate_watchlist_pair
from app.utils.request_guard import RequestGuardError, cache_key, guarded_cached

logger = get_logger(__name__)

kline_blp = Blueprint('kline', __name__)
kline_service = KlineService()


@kline_blp.route('/kline', methods=['GET'])
def get_kline():
    """
    Fetch OHLCV k-line bars.

    Query params:
        market: Market type (Crypto, USStock, Forex, Futures)
        symbol: Symbol or ticker
        timeframe: Bar size (1m, 5m, 15m, 30m, 1H, 4H, 1D, 1W)
        limit: Number of bars (default 300)
        before_time: Return bars before this Unix timestamp (optional)
    """
    try:
        market = (request.args.get('market', 'USStock') or '').strip()
        symbol = (request.args.get('symbol', '') or '').strip()
        timeframe = (request.args.get('timeframe', '1D') or '').strip()
        limit = int(request.args.get('limit', 300))
        limit = max(1, min(1000, limit))
        before_time = request.args.get('before_time') or request.args.get('beforeTime')
        
        if before_time:
            before_time = int(before_time)
        
        if not symbol:
            return jsonify({
                'code': 0,
                'msg': 'Missing symbol parameter',
                'data': None
            }), 400

        validation_err = validate_watchlist_pair(market, symbol)
        if validation_err:
            return jsonify({'code': 0, 'msg': validation_err, 'data': None}), 400
        
        logger.info(f"Requesting K-lines: {market}:{symbol}, timeframe={timeframe}, limit={limit}")
        
        klines = guarded_cached(
            cache_key("indicator_kline", market, symbol, timeframe, limit, before_time or ""),
            lambda: kline_service.get_kline(
                market=market,
                symbol=symbol,
                timeframe=timeframe,
                limit=limit,
                before_time=before_time
            ),
            ttl_sec=30,
            stale_ttl_sec=180,
            timeout_sec=10,
            namespace="indicator_kline",
            max_concurrent=8,
        )
        
        if not klines:
            msg = 'No data found'
            if market == 'Forex' and timeframe == '1m':
                msg = 'Forex 1-minute data requires Tiingo paid subscription'
            elif market == 'Forex' and timeframe in ('1W', '1M'):
                msg = 'No weekly/monthly data available for this period'
            return jsonify({
                'code': 0,
                'msg': msg,
                'data': [],
                'hint': 'tiingo_subscription' if (market == 'Forex' and timeframe == '1m') else None
            })
        
        return jsonify({
            'code': 1,
            'msg': 'success',
            'data': klines
        })
        
    except RequestGuardError as e:
        return jsonify({
            'code': 0,
            'msg': str(e),
            'data': None
        }), e.status_code
    except Exception as e:
        logger.error(f"Failed to fetch K-lines: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            'code': 0,
            'msg': f'Failed to fetch kline data: {str(e)}',
            'data': None
        }), 500


# openapi-compat: legacy import name
kline_bp = kline_blp
