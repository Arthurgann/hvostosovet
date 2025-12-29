alter table request_dedup
    alter column user_id drop not null,
    alter column response_json drop not null,
    add column if not exists status text not null default 'started',
    add column if not exists finished_at timestamptz null,
    add column if not exists error_text text null;
