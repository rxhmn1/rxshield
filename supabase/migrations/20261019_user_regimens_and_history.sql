-- ============================================================================
-- RxShield — Supabase Migration: User Regimens & Safety Check History
-- File: supabase/migrations/20261019_user_regimens_and_history.sql
-- Description: Sets up tables, Row Level Security (RLS), and ownership policies
--              for user-saved medication regimens and optional check history.
-- ============================================================================

-- Strict Privacy Tenet:
-- Tables store only user UUIDs, user-defined labels, and standardized medication IDs.
-- ZERO Patient Health Information (PHI) or Personally Identifiable Information (PII)
-- like patient names, birthdates, conditions, or clinical diagnoses are ever stored.

-- 1. Table: user_saved_regimens
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.user_saved_regimens (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
    title TEXT NOT NULL CHECK (char_length(title) <= 120),
    medication_ids TEXT[] NOT NULL CHECK (cardinality(medication_ids) > 0),
    notes TEXT DEFAULT '' CHECK (char_length(notes) <= 500),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Index on user_id for high-performance scoped lookups
CREATE INDEX IF NOT EXISTS idx_user_saved_regimens_user_id
    ON public.user_saved_regimens(user_id);

-- Enable Row Level Security (RLS)
ALTER TABLE public.user_saved_regimens ENABLE ROW LEVEL SECURITY;

-- Drop existing policies if re-running migration to ensure clean state
DROP POLICY IF EXISTS "Users can view their own regimens" ON public.user_saved_regimens;
DROP POLICY IF EXISTS "Users can create their own regimens" ON public.user_saved_regimens;
DROP POLICY IF EXISTS "Users can update their own regimens" ON public.user_saved_regimens;
DROP POLICY IF EXISTS "Users can delete their own regimens" ON public.user_saved_regimens;

-- RLS Policy: SELECT (Read only owned records)
CREATE POLICY "Users can view their own regimens"
    ON public.user_saved_regimens
    FOR SELECT
    USING (auth.uid() = user_id);

-- RLS Policy: INSERT (Insert only with current user ID)
CREATE POLICY "Users can create their own regimens"
    ON public.user_saved_regimens
    FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- RLS Policy: UPDATE (Update only owned records)
CREATE POLICY "Users can update their own regimens"
    ON public.user_saved_regimens
    FOR UPDATE
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- RLS Policy: DELETE (Delete only owned records)
CREATE POLICY "Users can delete their own regimens"
    ON public.user_saved_regimens
    FOR DELETE
    USING (auth.uid() = user_id);


-- 2. Table: user_safety_check_history (Optional Auditing / History)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.user_safety_check_history (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
    medication_ids TEXT[] NOT NULL,
    findings_count INTEGER DEFAULT 0 NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Index on user_id for history queries
CREATE INDEX IF NOT EXISTS idx_user_safety_check_history_user_id
    ON public.user_safety_check_history(user_id);

-- Enable Row Level Security (RLS)
ALTER TABLE public.user_safety_check_history ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view their own safety check history" ON public.user_safety_check_history;
DROP POLICY IF EXISTS "Users can insert their own safety check history" ON public.user_safety_check_history;
DROP POLICY IF EXISTS "Users can delete their own safety check history" ON public.user_safety_check_history;

-- RLS Policy: SELECT
CREATE POLICY "Users can view their own safety check history"
    ON public.user_safety_check_history
    FOR SELECT
    USING (auth.uid() = user_id);

-- RLS Policy: INSERT
CREATE POLICY "Users can insert their own safety check history"
    ON public.user_safety_check_history
    FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- RLS Policy: DELETE
CREATE POLICY "Users can delete their own safety check history"
    ON public.user_safety_check_history
    FOR DELETE
    USING (auth.uid() = user_id);


-- ============================================================================
-- VERIFICATION GUIDE: Two-User RLS Isolation Test
-- ============================================================================
--
-- How to apply this migration:
-- 1. Log in to your Supabase Dashboard: https://supabase.com/dashboard
-- 2. Navigate to your project -> "SQL Editor".
-- 3. Click "New Query", paste the entire contents of this file, and click "Run".
--
-- How to verify two-user isolation:
-- 1. In Supabase Dashboard -> "Authentication" -> "Users", create two users:
--      User A: user_a@example.com
--      User B: user_b@example.com
--
-- 2. Run the test script below in the SQL Editor:
--
--    -- Step A: Set session to User A
--    SET LOCAL role authenticated;
--    SET LOCAL request.jwt.claim.sub = '<UUID_OF_USER_A>';
--
--    INSERT INTO public.user_saved_regimens (user_id, title, medication_ids)
--    VALUES ('<UUID_OF_USER_A>', 'User A Heart Health', ARRAY['rxnorm:drug:202433']);
--
--    -- Step B: Set session to User B
--    SET LOCAL request.jwt.claim.sub = '<UUID_OF_USER_B>';
--
--    -- This query MUST return 0 rows (User B cannot see User A's data):
--    SELECT * FROM public.user_saved_regimens;
--
--    -- This insert MUST succeed for User B:
--    INSERT INTO public.user_saved_regimens (user_id, title, medication_ids)
--    VALUES ('<UUID_OF_USER_B>', 'User B Allergy Regimen', ARRAY['rxnorm:drug:153010']);
--
--    -- This query MUST return only User B's row (1 row):
--    SELECT * FROM public.user_saved_regimens;
--
--    -- This cross-user deletion attempt MUST delete 0 rows:
--    DELETE FROM public.user_saved_regimens WHERE user_id = '<UUID_OF_USER_A>';
-- ============================================================================
