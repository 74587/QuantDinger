CREATE TABLE IF NOT EXISTS qd_exchange_order_pnl (
    credential_id INTEGER NOT NULL,
    exchange_id VARCHAR(50) NOT NULL,
    market_type VARCHAR(20) NOT NULL,
    symbol VARCHAR(80) NOT NULL,
    exchange_order_id VARCHAR(160) NOT NULL,
    expected_quantity NUMERIC(36,18) NOT NULL DEFAULT 0,
    report JSONB NOT NULL DEFAULT '{}'::jsonb,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (credential_id, exchange_id, market_type, symbol, exchange_order_id)
);
CREATE INDEX IF NOT EXISTS idx_exchange_pnl_checked ON qd_exchange_order_pnl(credential_id, checked_at);
