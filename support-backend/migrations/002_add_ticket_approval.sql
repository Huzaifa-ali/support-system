-- ============================================================
-- SUPPORT SYSTEM - 002 ADD TICKET APPROVAL GATE
-- Run this in Supabase SQL Editor AFTER 001_initial_schema.sql
-- ============================================================

ALTER TABLE tickets
    ADD COLUMN IF NOT EXISTS approval_status text NOT NULL DEFAULT 'approved'
        CHECK (approval_status IN ('pending_approval', 'approved')),
    ADD COLUMN IF NOT EXISTS approved_by uuid REFERENCES users(id),
    ADD COLUMN IF NOT EXISTS approved_at timestamptz;

CREATE INDEX IF NOT EXISTS idx_tickets_project_approval
    ON tickets(project_id, approval_status);
