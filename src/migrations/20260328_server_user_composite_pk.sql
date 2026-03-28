-- Migration: ensure server_user rows are keyed per (user_id, guild_id)
--
-- Reason: /user_profile looks up by (user_id, guild_id) but historical schema used PRIMARY KEY (user_id)
-- which caused cross-guild overwrites and missing lookups.

BEGIN;

-- If the old schema exists, it likely has a PK on (user_id). We drop it and add the composite PK.
-- This will fail if duplicates exist for the same (user_id, guild_id). In practice, old schema
-- could only store one guild per user, so duplicates are unexpected.
ALTER TABLE server_user DROP CONSTRAINT IF EXISTS server_user_pkey;
ALTER TABLE server_user ADD CONSTRAINT server_user_pkey PRIMARY KEY (user_id, guild_id);

COMMIT;

