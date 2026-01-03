-- 003_patch_users_plan_sessions.sql

-- 1) users.plan: CHECK (free | pro)
do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'users_plan_check'
  ) then
    alter table users
      add constraint users_plan_check
      check (plan in ('free', 'pro'));
  end if;
end $$;

-- 2) sessions.user_id: NOT NULL + ON DELETE CASCADE
alter table sessions
  alter column user_id set not null;

do $$
begin
  if exists (
    select 1
    from pg_constraint
    where conname = 'sessions_user_id_fkey'
  ) then
    alter table sessions drop constraint sessions_user_id_fkey;
  end if;

  alter table sessions
    add constraint sessions_user_id_fkey
    foreign key (user_id) references users(id) on delete cascade;
end $$;
