-- 005_patch_pro_vision_limits.sql
-- Лимит фото для Pro Vision (месячный счётчик)

alter table users
  add column if not exists vision_images_used int not null default 0;

alter table users
  add column if not exists vision_images_reset_at timestamptz not null
    default (date_trunc('month', now()) + interval '1 month');

create index if not exists users_vision_images_reset_at_idx
  on users(vision_images_reset_at);
