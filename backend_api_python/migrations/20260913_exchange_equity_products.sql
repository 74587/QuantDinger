ALTER TABLE qd_market_symbols ADD COLUMN IF NOT EXISTS product_type VARCHAR(32) NOT NULL DEFAULT 'crypto';
ALTER TABLE qd_market_symbols ADD COLUMN IF NOT EXISTS api_family VARCHAR(24) NOT NULL DEFAULT 'spot';
ALTER TABLE qd_market_symbols ADD COLUMN IF NOT EXISTS underlying_market VARCHAR(32) NOT NULL DEFAULT '';
ALTER TABLE qd_market_symbols ADD COLUMN IF NOT EXISTS underlying_symbol VARCHAR(50) NOT NULL DEFAULT '';
ALTER TABLE qd_market_symbols ADD COLUMN IF NOT EXISTS product_meta JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE qd_market_symbols ADD COLUMN IF NOT EXISTS metadata_updated_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_market_symbols_product_catalog
  ON qd_market_symbols(market, exchange, market_type, product_type, is_active);

ALTER TABLE qd_watchlist DROP CONSTRAINT IF EXISTS uq_watchlist_asset;
DROP INDEX IF EXISTS uq_watchlist_asset;
CREATE UNIQUE INDEX IF NOT EXISTS uq_watchlist_market_context
  ON qd_watchlist(user_id, market, symbol, exchange_id, market_type, instrument_id);
