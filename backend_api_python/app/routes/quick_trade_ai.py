"""AI decision boundary for Quick Trade entry orders."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from flask import jsonify

from app.services.ai_decision_context import build_quick_trade_decision_context
from app.services.ai_decision_filter import AIDecisionFilter, AIDecisionRequest


def maybe_reject_quick_trade(
    context: Mapping[str, Any],
    record_trade: Callable[..., None],
) -> Any | None:
    body = context.get("body") or {}
    if not bool(body.get("ai_decision_filter")):
        return None

    market_type = str(context.get("market_type") or "")
    side = str(context.get("side") or "")
    base_qty = float(context.get("base_qty") or 0)
    decision_action = (
        "open_long" if side == "buy" else "close_long"
    ) if market_type == "spot" else (
        "open_long" if side == "buy" else "open_short"
    )
    decision_price = float(context.get("price") or 0)
    if decision_price <= 0 and base_qty > 0:
        decision_price = float(context.get("order_notional_usdt") or 0) / base_qty

    user_id = int(context.get("user_id") or 0)
    symbol = str(context.get("symbol") or "")
    order_type = str(context.get("order_type") or "market")
    leverage = float(context.get("leverage") or 1)
    source = str(context.get("source") or "manual")
    usdt_amount = float(context.get("usdt_amount") or 0)
    tp_price = float(context.get("tp_price") or 0)
    sl_price = float(context.get("sl_price") or 0)
    margin_mode = str(context.get("margin_mode") or "")
    decision = AIDecisionFilter().evaluate(
        AIDecisionRequest(
            user_id=user_id,
            source_type="quick_trade",
            source_id=int(context.get("credential_id") or 0),
            symbol=symbol,
            action=decision_action,
            market_type=market_type,
            order_type=order_type,
            quantity=base_qty,
            reference_price=decision_price,
            leverage=leverage,
            reason=source,
            context={
                "source": source,
                "amount_quote": usdt_amount,
                "take_profit_price": tp_price,
                "stop_loss_price": sl_price,
                "margin_mode": margin_mode,
                **build_quick_trade_decision_context(context),
            },
        ),
        enabled=True,
    )
    if decision.allowed:
        return None

    record_trade(
        user_id=user_id,
        credential_id=context.get("credential_id"),
        exchange_id=context.get("exchange_id"),
        symbol=symbol,
        side=side,
        order_type=order_type,
        amount=usdt_amount,
        price=decision_price,
        leverage=leverage,
        market_type=market_type,
        tp_price=tp_price,
        sl_price=sl_price,
        status="ai_rejected",
        exchange_order_id="",
        filled=0.0,
        avg_price=0.0,
        error_msg=decision.reason,
        source=source,
        raw_result={"ai_decision": decision.public_dict()},
    )
    return jsonify({
        "code": 0,
        "msg": "aiDecisionFilter.rejected",
        "ai_rejected": True,
        "data": {"ai_decision": decision.public_dict()},
    })
