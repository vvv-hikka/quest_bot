-- QUEST Bot — clients table

create table if not exists public.quest_clients (
  id uuid primary key default gen_random_uuid(),
  telegram_id bigint unique not null,
  telegram_username text,

  full_name text,
  phone text,
  email text,
  specialty text,
  resume_link text,
  resume_file_id text,
  portfolio text,
  soft_skills text,
  work_values text,

  profile_complete boolean not null default false,
  survey_step text not null default 'not_started',
  reminders_sent int not null default 0,
  next_reminder_at timestamptz,

  created_at timestamptz not null default now(),
  completed_at timestamptz
);

create index if not exists idx_quest_clients_tg_id on public.quest_clients(telegram_id);
create index if not exists idx_quest_clients_incomplete on public.quest_clients(profile_complete, next_reminder_at)
  where profile_complete = false;

alter table public.quest_clients enable row level security;
create policy "Service full access" on public.quest_clients for all using (true);
