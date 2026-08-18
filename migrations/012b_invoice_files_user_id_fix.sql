-- Documents a fix already applied live to Supabase on 2026-07-18.
-- Do not re-run — column and policy already exist in production.

ALTER TABLE invoice_files
  ADD COLUMN IF NOT EXISTS user_id uuid NOT NULL;

CREATE POLICY IF NOT EXISTS invoice_files_user_policy
  ON invoice_files
  FOR ALL
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());
