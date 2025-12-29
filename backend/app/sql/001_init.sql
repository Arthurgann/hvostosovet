create extension if not exists pgcrypto;

create table if not exists users (
    id uuid primary key default gen_random_uuid(),
    telegram_user_id bigint unique not null,
    created_at timestamptz not null default now(),
    plan text not null,
    locale text null,
    last_seen_at timestamptz null,
    research_used int not null default 0,
    research_limit int not null default 2,
    research_reset_at timestamptz not null
);

create table if not exists rate_limits (
    user_id uuid primary key references users(id),
    window_type text not null,
    window_start_at timestamptz not null,
    window_end_at timestamptz not null,
    count int not null,
    last_request_at timestamptz not null,
    cooldown_until timestamptz null
);
create index if not exists rate_limits_window_end_at_idx on rate_limits(window_end_at);

create table if not exists sessions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid references users(id),
    session_context jsonb not null,
    expires_at timestamptz not null,
    updated_at timestamptz not null
);
create index if not exists sessions_user_id_idx on sessions(user_id);
create index if not exists sessions_expires_at_idx on sessions(expires_at);

create table if not exists pets (
    id uuid primary key default gen_random_uuid(),
    user_id uuid references users(id),
    type text not null,
    name text null,
    sex text not null,
    birth_date date null,
    age_text text null,
    breed text null,
    created_at timestamptz not null default now(),
    archived_at timestamptz null
);
create index if not exists pets_user_id_idx on pets(user_id);

create table if not exists interactions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid references users(id),
    pet_id uuid references pets(id),
    scenario text not null,
    mode text not null,
    question_text text not null,
    answer_text text not null,
    summary text not null,
    created_at timestamptz not null default now()
);
create index if not exists interactions_pet_id_created_at_idx on interactions(pet_id, created_at desc);
create index if not exists interactions_user_id_created_at_idx on interactions(user_id, created_at desc);

create table if not exists media_assets (
    id uuid primary key default gen_random_uuid(),
    user_id uuid references users(id),
    pet_id uuid references pets(id),
    type text not null,
    storage_url text not null,
    mime text not null,
    size_bytes int not null,
    created_at timestamptz not null default now(),
    expires_at timestamptz null,
    deleted_at timestamptz null
);
create index if not exists media_assets_user_id_created_at_idx on media_assets(user_id, created_at desc);
create index if not exists media_assets_expires_at_idx on media_assets(expires_at);

create table if not exists llm_policies (
    key text primary key,
    provider text not null,
    model text not null,
    temperature numeric not null,
    max_tokens int not null,
    enabled bool not null default true,
    updated_at timestamptz not null default now()
);

create table if not exists request_dedup (
    request_id uuid primary key,
    user_id uuid references users(id) null,
    created_at timestamptz not null default now(),
    response_json jsonb null,
    status text not null default 'started',
    finished_at timestamptz null,
    error_text text null
);
create index if not exists request_dedup_user_id_created_at_idx on request_dedup(user_id, created_at desc);
