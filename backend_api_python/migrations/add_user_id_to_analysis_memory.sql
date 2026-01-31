-- Migration: Add user_id column to qd_analysis_memory table
-- This allows filtering analysis history by user
-- Run this migration to update existing databases

-- Add user_id column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'qd_analysis_memory' AND column_name = 'user_id'
    ) THEN
        ALTER TABLE qd_analysis_memory ADD COLUMN user_id INT;
        
        -- Create index for efficient user-based queries
        CREATE INDEX IF NOT EXISTS idx_analysis_memory_user ON qd_analysis_memory(user_id);
        
        RAISE NOTICE 'Added user_id column to qd_analysis_memory';
    ELSE
        RAISE NOTICE 'user_id column already exists in qd_analysis_memory';
    END IF;
END $$;
