-- Public research data only. Anonymous access is SELECT-only; imports use service_role.
begin;

create table if not exists public.research_datasets (
  dataset_key text primary key,
  title text not null,
  phase text not null check (phase in ('earlier', 'later')),
  source_path text not null,
  source_sha256 text not null check (length(source_sha256) = 64),
  market_count integer not null,
  trade_leg_count integer not null,
  taker_count integer not null,
  price_count integer not null,
  status text not null default 'loading' check (status in ('loading','ready'))
);

create table if not exists public.research_markets (
  dataset_key text not null references public.research_datasets(dataset_key),
  market_id text not null,
  condition_id text not null,
  event_id text not null,
  economic_cluster_id text not null,
  question text not null,
  category text not null,
  trading_start bigint,
  scheduled_end bigint,
  label_available_at bigint not null,
  yes_outcome smallint not null check (yes_outcome in (0,1)),
  yes_token_id text not null,
  no_token_id text not null,
  source_url text not null,
  primary key (dataset_key, market_id)
);

create table if not exists public.research_wallets (
  address text primary key check (address ~ '^0x[0-9a-f]{40}$')
);

-- One all-side record per source CSV row. taker records are flags, never appended twice.
create table if not exists public.research_trades (
  dataset_key text not null,
  market_id text not null,
  source_row integer not null,
  observed_at bigint not null,
  wallet text not null references public.research_wallets(address),
  side text not null check (side in ('BUY','SELL')),
  outcome text not null check (outcome in ('Yes','No')),
  size_shares double precision not null check (size_shares >= 0),
  price double precision not null check (price between 0 and 1),
  is_taker boolean not null,
  primary key (dataset_key, market_id, source_row),
  foreign key (dataset_key, market_id) references public.research_markets(dataset_key, market_id)
);
create index if not exists research_trades_market_time on public.research_trades(dataset_key,market_id,observed_at);
create index if not exists research_trades_wallet_time on public.research_trades(wallet,observed_at);

create table if not exists public.research_prices (
  dataset_key text not null,
  market_id text not null,
  source_row integer not null,
  outcome text not null check (outcome in ('Yes','No')),
  observed_at bigint not null,
  available_at bigint not null,
  resolution_seconds integer not null check (resolution_seconds >= 0),
  price double precision not null check (price between 0 and 1),
  primary key (dataset_key,market_id,source_row),
  foreign key (dataset_key,market_id) references public.research_markets(dataset_key,market_id)
);
create index if not exists research_prices_market_available on public.research_prices(dataset_key,market_id,available_at);

create table if not exists public.research_returns (
  wallet text not null references public.research_wallets(address),
  market_id text not null,
  economic_cluster_id text not null,
  category text not null,
  available_at bigint not null,
  reported_realized_pnl_usdc double precision,
  estimated_entry_basis_usdc double precision,
  reported_return_proxy double precision,
  usable boolean not null,
  primary key (wallet,market_id)
);

create table if not exists public.research_experiments (
  experiment_key text primary key,
  title text not null,
  fit_at bigint not null,
  horizon_days integer not null,
  summary jsonb not null,
  source_sha256 text not null,
  status text not null default 'loading' check (status in ('loading','ready'))
);

create table if not exists public.research_candidates (
  experiment_key text not null references public.research_experiments(experiment_key),
  wallet text not null references public.research_wallets(address),
  group_name text not null check (group_name in ('skilled_proxy','unskilled_proxy','unknown')),
  activity_rank integer not null,
  resolved_markets integer not null,
  earlier_comparable_markets integer not null,
  fraction_above_winner_mean double precision,
  mean_reported_return_proxy double precision,
  primary key (experiment_key,wallet)
);

create table if not exists public.research_predictions (
  experiment_key text not null references public.research_experiments(experiment_key),
  market_id text not null,
  forecast_at bigint not null,
  window_end bigint not null,
  group_name text not null check (group_name in ('skilled_proxy','unskilled_proxy','unknown')),
  side text not null check (side in ('BUY','SELL')),
  group_size integer not null,
  actual_wallets integer not null,
  predicted_wallets double precision not null,
  historical_rate_wallets double precision not null,
  recent_wallets integer not null,
  primary key (experiment_key,market_id,forecast_at,group_name,side),
  check (actual_wallets between 0 and group_size),
  check (predicted_wallets between 0 and group_size)
);

create table if not exists public.research_artifacts (
  source_path text primary key,
  object_path text not null unique,
  sha256 text not null check (length(sha256)=64),
  bytes bigint not null,
  content_type text not null
);

-- No write privileges/policies for website visitors. service_role remains import-only.
do $$
declare name text;
begin
  foreach name in array array['research_datasets','research_markets','research_wallets','research_trades',
    'research_prices','research_returns','research_experiments','research_candidates','research_predictions','research_artifacts']
  loop
    execute format('alter table public.%I enable row level security',name);
    execute format('revoke all on public.%I from anon, authenticated',name);
    execute format('grant select on public.%I to anon, authenticated',name);
    execute format('grant all on public.%I to service_role',name);
  end loop;
end $$;

drop policy if exists research_public_read on public.research_datasets;
create policy research_public_read on public.research_datasets for select to anon,authenticated using (status='ready');
drop policy if exists research_public_read on public.research_markets;
create policy research_public_read on public.research_markets for select to anon,authenticated using
  (exists(select 1 from public.research_datasets d where d.dataset_key=research_markets.dataset_key and d.status='ready'));
drop policy if exists research_public_read on public.research_trades;
create policy research_public_read on public.research_trades for select to anon,authenticated using
  (exists(select 1 from public.research_datasets d where d.dataset_key=research_trades.dataset_key and d.status='ready'));
drop policy if exists research_public_read on public.research_prices;
create policy research_public_read on public.research_prices for select to anon,authenticated using
  (exists(select 1 from public.research_datasets d where d.dataset_key=research_prices.dataset_key and d.status='ready'));
drop policy if exists research_public_read on public.research_experiments;
create policy research_public_read on public.research_experiments for select to anon,authenticated using(status='ready');
drop policy if exists research_public_read on public.research_candidates;
create policy research_public_read on public.research_candidates for select to anon,authenticated using
  (exists(select 1 from public.research_experiments e where e.experiment_key=research_candidates.experiment_key and e.status='ready'));
drop policy if exists research_public_read on public.research_predictions;
create policy research_public_read on public.research_predictions for select to anon,authenticated using
  (exists(select 1 from public.research_experiments e where e.experiment_key=research_predictions.experiment_key and e.status='ready'));
drop policy if exists research_public_read on public.research_wallets;
create policy research_public_read on public.research_wallets for select to anon,authenticated using(true);
drop policy if exists research_public_read on public.research_returns;
create policy research_public_read on public.research_returns for select to anon,authenticated using(true);
drop policy if exists research_public_read on public.research_artifacts;
create policy research_public_read on public.research_artifacts for select to anon,authenticated using(true);

commit;
