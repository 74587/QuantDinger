ALTER TABLE qd_strategy_trades ADD COLUMN IF NOT EXISTS commission_breakdown JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE qd_strategy_trades ADD COLUMN IF NOT EXISTS exchange_order_id VARCHAR(128) NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_strategy_trades_order_fill ON qd_strategy_trades(pending_order_id, exchange_order_id);
ALTER TABLE qd_execution_events ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
CREATE INDEX IF NOT EXISTS idx_execution_events_retry ON qd_execution_events(next_attempt_at, id) WHERE processed_at IS NULL;

-- Preserve fractional shares and small crypto fills across every ledger writer.
DO $$
DECLARE target RECORD;
BEGIN
    FOR target IN
        SELECT table_name, column_name FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name IN ('qd_strategy_trades', 'qd_strategy_positions', 'qd_grid_resting_orders',
                             'qd_grid_cells', 'pending_orders', 'qd_execution_events',
                             'strategy_order_fills', 'qd_quick_trades', 'qd_live_order_bindings')
          AND data_type = 'numeric' AND numeric_scale < 18
          AND column_name IN ('amount', 'size', 'quantity', 'filled', 'filled_quantity', 'processed_fill_qty',
                              'cumulative_quantity', 'observed_filled', 'filled_amount', 'leg_size', 'price', 'avg_price',
                              'avg_fill_price', 'entry_price', 'leg_entry_price', 'value', 'commission',
                              'commission_quote', 'fee', 'profit', 'matched_entry_price', 'grid_matched_profit')
    LOOP
        EXECUTE format('ALTER TABLE %I ALTER COLUMN %I TYPE NUMERIC(38,18)', target.table_name, target.column_name);
    END LOOP;
END $$;
