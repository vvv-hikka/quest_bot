-- Воронка: история переходов пользователей по шагам анкеты.
-- По этой таблице можно строить воронку и путь каждого пользователя.

create table if not exists public.quest_funnel_events (
  id uuid primary key default gen_random_uuid(),
  telegram_id bigint not null,
  step text not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_quest_funnel_events_telegram_id
  on public.quest_funnel_events(telegram_id);
create index if not exists idx_quest_funnel_events_created_at
  on public.quest_funnel_events(created_at);
create index if not exists idx_quest_funnel_events_step
  on public.quest_funnel_events(step);

alter table public.quest_funnel_events enable row level security;
create policy "Service full access" on public.quest_funnel_events for all using (true);

comment on table public.quest_funnel_events is 'Каждое событие = пользователь перешёл на шаг step в момент created_at. Порядок по created_at даёт путь пользователя по воронке.';

-- Пример: воронка по последнему шагу каждого пользователя (в Supabase SQL Editor):
-- with last_step as (
--   select distinct on (telegram_id) telegram_id, step
--   from quest_funnel_events
--   order by telegram_id, created_at desc
-- )
-- select step, count(*) from last_step group by step order by step;
