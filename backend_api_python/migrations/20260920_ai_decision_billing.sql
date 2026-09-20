ALTER TABLE qd_ai_decisions
    ADD COLUMN IF NOT EXISTS billing_json JSONB NOT NULL DEFAULT '{}'::jsonb;
