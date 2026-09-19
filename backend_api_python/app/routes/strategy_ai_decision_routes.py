"""AI decision audit routes for live strategies."""

from flask import g, jsonify, request

from app.routes.strategy_blueprint import strategy_blp
from app.routes.strategy_services import get_strategy_service
from app.services.ai_decision_filter import list_ai_decisions
from app.utils.auth import login_required


@strategy_blp.route('/strategies/ai-decisions', methods=['GET'])
@login_required
def get_strategy_ai_decisions():
    strategy_id = int(request.args.get('id') or 0)
    if strategy_id <= 0:
        return jsonify({'code': 0, 'msg': 'strategyV2.strategyIdRequired'}), 400
    strategy = get_strategy_service().get_strategy(strategy_id, user_id=int(g.user_id))
    if not strategy:
        return jsonify({'code': 0, 'msg': 'strategyV2.strategyNotFound'}), 404
    rows = list_ai_decisions(
        user_id=int(g.user_id),
        source_type='strategy',
        source_id=strategy_id,
        limit=int(request.args.get('limit') or 100),
    )
    return jsonify({'code': 1, 'msg': 'common.success', 'data': rows})
