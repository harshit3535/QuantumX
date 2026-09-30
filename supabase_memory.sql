-- Run once in a free Supabase project's SQL Editor.
create table if not exists public.astra_memory (
  session_id text primary key,
  payload jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);
create index if not exists astra_memory_updated_at_idx on public.astra_memory(updated_at desc);
