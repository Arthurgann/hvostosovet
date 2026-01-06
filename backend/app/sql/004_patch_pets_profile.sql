-- 004_patch_pets_profile.sql

alter table pets
  add column if not exists profile jsonb not null default '{}'::jsonb;

-- На всякий: updated_at (удобно для синхронизации)
alter table pets
  add column if not exists updated_at timestamptz not null default now();

create index if not exists pets_user_id_updated_at_idx
  on pets(user_id, updated_at desc);
