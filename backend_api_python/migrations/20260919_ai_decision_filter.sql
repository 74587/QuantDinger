CREATE TABLE IF NOT EXISTS qd_ai_decisions (
    id BIGSERIAL PRIMARY KEY,
    decision_uid VARCHAR(64) NOT NULL UNIQUE,
    user_id INTEGER NOT NULL DEFAULT 0,
    source_type VARCHAR(24) NOT NULL,
    source_id BIGINT NOT NULL DEFAULT 0,
    strategy_run_id BIGINT NOT NULL DEFAULT 0,
    order_intent_id BIGINT NOT NULL DEFAULT 0,
    symbol VARCHAR(80) NOT NULL DEFAULT '',
    action VARCHAR(40) NOT NULL DEFAULT '',
    market_type VARCHAR(24) NOT NULL DEFAULT '',
    provider VARCHAR(24) NOT NULL DEFAULT 'none',
    model VARCHAR(120) NOT NULL DEFAULT '',
    decision VARCHAR(24) NOT NULL,
    allowed BOOLEAN NOT NULL DEFAULT TRUE,
    confidence DECIMAL(8, 6),
    reason TEXT NOT NULL DEFAULT '',
    fallback_reason TEXT NOT NULL DEFAULT '',
    probabilities_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    checks_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    request_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_decisions_strategy
    ON qd_ai_decisions(source_type, source_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_decisions_user
    ON qd_ai_decisions(user_id, created_at DESC);
