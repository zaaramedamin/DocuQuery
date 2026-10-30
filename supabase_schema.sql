-- ══════════════════════════════════════════════════════════════════
-- DocuQuery database schema
--
-- Safe to run on a fresh project AND on an existing DocuQuery database:
-- every statement is idempotent. Paste the whole file into the Supabase
-- SQL editor and run it. Re-run it after pulling updates.
--
-- The backend talks to Supabase with the service_role / secret key and
-- enforces per-user access itself (every query is filtered by user_id).
-- Row Level Security below is defence in depth: it blocks anyone who
-- reaches the database with the public (anon) key.
-- ══════════════════════════════════════════════════════════════════

-- Enable the pgvector extension to work with embedding vectors
create extension if not exists vector;

-- ══════════════════════════════════════════════════════════════════
-- Document chunks + their vector embeddings
-- ══════════════════════════════════════════════════════════════════
create table if not exists document_chunks (
  id bigserial primary key,
  filename text not null,
  chunk_index integer not null,
  text text not null,
  page integer not null,
  embedding vector(384) not null  -- 384 dimensions: gemini-embedding-2 with output_dimensionality=384
);

-- Owner of the chunk (private libraries)
alter table document_chunks
  add column if not exists user_id uuid references auth.users(id) on delete cascade;

-- Full-text search column for hybrid (keyword + vector) retrieval.
-- 'simple' = no stemming / stop-words, so it works for any language.
alter table document_chunks
  add column if not exists fts tsvector
  generated always as (to_tsvector('simple', "text")) stored;

-- Vector index (HNSW, cosine distance)
create index if not exists document_chunks_embedding_hnsw_idx
  on document_chunks
  using hnsw (embedding vector_cosine_ops);

create index if not exists document_chunks_fts_idx
  on document_chunks using gin (fts);

create index if not exists document_chunks_user_file_idx
  on document_chunks (user_id, filename);

-- ══════════════════════════════════════════════════════════════════
-- Documents: one row per uploaded source (PDF, DOCX, TXT, MD, image, URL)
-- ══════════════════════════════════════════════════════════════════
create table if not exists documents (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  filename text not null,                       -- display name, unique per user
  file_type text not null default 'pdf',        -- pdf | docx | txt | md | image | url
  storage_key text,                             -- object key in the "documents" bucket
  size_bytes bigint not null default 0,
  page_count integer not null default 0,
  chunks_count integer not null default 0,
  summary text,                                 -- AI summary generated on upload
  suggested_questions jsonb not null default '[]'::jsonb,
  source_url text,                              -- set for web-page sources
  pages jsonb,                                  -- extracted text per page (non-PDF types, for the viewer)
  created_at timestamptz not null default now(),
  unique (user_id, filename)
);

-- Free-form labels for organising a large library (added after the first release).
alter table documents
  add column if not exists tags text[] not null default '{}';

-- A source can be put in one named folder (shared name = same folder).
alter table documents
  add column if not exists folder text;

create index if not exists documents_user_idx on documents (user_id, created_at desc);
create index if not exists documents_user_folder_idx on documents (user_id, folder) where folder is not null;

-- ══════════════════════════════════════════════════════════════════
-- Hybrid search: vector similarity + keyword match, fused with
-- Reciprocal Rank Fusion (RRF). Always scoped to one user.
--
--   query_tsquery  a to_tsquery() string built by the backend, e.g.
--                  'refund | policy | days'  (empty string = vector only)
-- ══════════════════════════════════════════════════════════════════
-- The first release had no filter_filenames argument. A second overload would make
-- calls ambiguous, so drop the old signature first.
drop function if exists hybrid_search(uuid, vector, text, int, text, int, float);

create or replace function hybrid_search (
  p_user_id uuid,
  query_embedding vector(384),
  query_tsquery text,
  match_count int default 15,
  filter_filename text default null,
  rrf_k int default 60,
  min_similarity float default 0.2,
  filter_filenames text[] default null     -- search inside this set of documents (tags / folders)
)
returns table (
  id bigint,
  filename text,
  chunk_index int,
  text text,
  page int,
  similarity float,
  score float
)
language plpgsql
as $$
#variable_conflict use_column
begin
  -- With several users sharing one HNSW index, filtering by user_id after
  -- the index scan can starve results. Iterative scans (pgvector >= 0.8)
  -- keep scanning until enough rows pass the filter. Ignored if unsupported.
  begin
    perform set_config('hnsw.iterative_scan', 'strict_order', true);
  exception when others then
    null;
  end;

  return query
  with vec as (
    select
      c.id as chunk_id,
      row_number() over (order by c.embedding <=> query_embedding) as rnk,
      1 - (c.embedding <=> query_embedding) as sim
    from document_chunks c
    where c.user_id = p_user_id
      and (filter_filename is null or c.filename = filter_filename)
      and (filter_filenames is null or c.filename = any(filter_filenames))
      and 1 - (c.embedding <=> query_embedding) > min_similarity
    order by c.embedding <=> query_embedding
    limit match_count * 2
  ),
  kw as (
    select
      c.id as chunk_id,
      row_number() over (order by ts_rank_cd(c.fts, q.tsq) desc) as rnk
    from document_chunks c
    cross join (select to_tsquery('simple', query_tsquery) as tsq) q
    where query_tsquery <> ''
      and c.user_id = p_user_id
      and (filter_filename is null or c.filename = filter_filename)
      and (filter_filenames is null or c.filename = any(filter_filenames))
      and c.fts @@ q.tsq
    order by ts_rank_cd(c.fts, q.tsq) desc
    limit match_count * 2
  ),
  fused as (
    select
      coalesce(vec.chunk_id, kw.chunk_id) as chunk_id,
      coalesce(1.0 / (rrf_k + vec.rnk), 0) + coalesce(1.0 / (rrf_k + kw.rnk), 0) as fused_score,
      vec.sim as sim
    from vec
    full outer join kw on vec.chunk_id = kw.chunk_id
  )
  select
    c.id,
    c.filename,
    c.chunk_index,
    c.text,
    c.page,
    coalesce(f.sim, 0)::float,
    f.fused_score::float
  from fused f
  join document_chunks c on c.id = f.chunk_id
  order by f.fused_score desc
  limit match_count;
end;
$$;

-- ══════════════════════════════════════════════════════════════════
-- Saved chat history
-- ══════════════════════════════════════════════════════════════════
create table if not exists conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null default 'New chat',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists conversations_user_updated_idx
  on conversations (user_id, updated_at desc);

create table if not exists messages (
  id uuid primary key default gen_random_uuid(),
  seq bigint generated always as identity,      -- strict ordering inside a conversation
  conversation_id uuid not null references conversations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('user', 'assistant')),
  content text not null default '',
  sources jsonb not null default '[]'::jsonb,
  question text,                                -- the question an assistant message answered
  feedback text check (feedback in ('up', 'down')),
  created_at timestamptz not null default now()
);

create index if not exists messages_conversation_idx on messages (conversation_id, seq);
create index if not exists messages_user_created_idx on messages (user_id, created_at desc);

-- ══════════════════════════════════════════════════════════════════
-- Sharing: unguessable links to a chat (read-only view) or a source
-- (the recipient can add a copy to their own library)
-- ══════════════════════════════════════════════════════════════════
create table if not exists shares (
  id uuid primary key default gen_random_uuid(),
  token text not null unique,
  user_id uuid not null references auth.users(id) on delete cascade,
  kind text not null check (kind in ('document', 'conversation')),
  conversation_id uuid references conversations(id) on delete cascade,
  document_filename text,     -- by name, not id: re-uploading a document replaces its row
  created_at timestamptz not null default now(),
  check (
    (kind = 'conversation' and conversation_id is not null) or
    (kind = 'document' and document_filename is not null)
  )
);

create unique index if not exists shares_one_per_conversation
  on shares (conversation_id) where kind = 'conversation';
create unique index if not exists shares_one_per_document
  on shares (user_id, document_filename) where kind = 'document';

-- Copy a document's chunks (with their embeddings) to another user, no re-embedding needed.
create or replace function clone_document_chunks (
  p_src_user uuid,
  p_dst_user uuid,
  p_filename text,
  p_new_filename text
)
returns int
language plpgsql
as $$
declare
  copied int;
begin
  insert into document_chunks (user_id, filename, chunk_index, text, page, embedding)
  select p_dst_user, p_new_filename, c.chunk_index, c.text, c.page, c.embedding
  from document_chunks c
  where c.user_id = p_src_user and c.filename = p_filename;
  get diagnostics copied = row_count;
  return copied;
end;
$$;

-- ══════════════════════════════════════════════════════════════════
-- Profiles: display name, plan (free / pro) and preferences.
-- Written ONLY by the backend (service_role). Signed-in users may read their own
-- row but get no write policy, so nobody can give themselves the Pro plan.
-- ══════════════════════════════════════════════════════════════════
create table if not exists profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  plan text not null default 'free' check (plan in ('free', 'pro')),
  subscription_status text,                      -- active / canceled
  current_period_end timestamptz,
  cancel_at_period_end boolean not null default false,
  settings jsonb not null default '{}'::jsonb,   -- language, theme, answer style, custom instructions…
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- ══════════════════════════════════════════════════════════════════
-- Storage bucket for the original uploaded files
-- Keeps uploads durable across redeploys on ephemeral-filesystem hosts
-- (accessed by the backend with the service_role key only).
-- ══════════════════════════════════════════════════════════════════
insert into storage.buckets (id, name, public)
values ('documents', 'documents', false)
on conflict (id) do nothing;

-- ══════════════════════════════════════════════════════════════════
-- User feedback table for thumbs-up / thumbs-down on AI responses
-- ══════════════════════════════════════════════════════════════════
create table if not exists feedback (
  id bigserial primary key,
  message_id text not null,
  feedback text not null,    -- 'up' or 'down'
  question text default '',
  answer text default '',
  created_at timestamptz default now()
);

alter table feedback
  add column if not exists user_id uuid references auth.users(id) on delete cascade;

-- ══════════════════════════════════════════════════════════════════
-- Row Level Security (defence in depth; the service_role key bypasses it)
-- ══════════════════════════════════════════════════════════════════
alter table document_chunks enable row level security;
alter table documents       enable row level security;
alter table conversations   enable row level security;
alter table messages        enable row level security;
alter table feedback        enable row level security;
alter table shares          enable row level security;
alter table profiles        enable row level security;

drop policy if exists "chunks_owner_select" on document_chunks;
create policy "chunks_owner_select" on document_chunks
  for select using (auth.uid() = user_id);

drop policy if exists "documents_owner_all" on documents;
create policy "documents_owner_all" on documents
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "conversations_owner_all" on conversations;
create policy "conversations_owner_all" on conversations
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "messages_owner_all" on messages;
create policy "messages_owner_all" on messages
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "shares_owner_all" on shares;
create policy "shares_owner_all" on shares
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Read-only for the owner on purpose (see the profiles table above).
drop policy if exists "profiles_owner_select" on profiles;
create policy "profiles_owner_select" on profiles
  for select using (auth.uid() = user_id);

drop policy if exists "feedback_owner_insert" on feedback;
create policy "feedback_owner_insert" on feedback
  for insert with check (auth.uid() = user_id);

-- Search functions are for the backend only (service_role). Without this,
-- Postgres grants EXECUTE to everyone, including the public anon key.
revoke execute on function hybrid_search(uuid, vector, text, int, text, int, float, text[])
  from public, anon, authenticated;
revoke execute on function clone_document_chunks(uuid, uuid, text, text)
  from public, anon, authenticated;

-- The pre-accounts functions are no longer used and were not user-scoped.
drop function if exists match_documents(vector, float, int, text);
drop function if exists list_document_filenames();

-- ══════════════════════════════════════════════════════════════════
-- OPTIONAL — adopt documents uploaded BEFORE accounts existed.
-- Old rows have no owner, so nobody can see them. Sign up in the app,
-- copy your user id (Supabase dashboard → Authentication → Users), then
-- run the two statements below with your id (remove the leading "-- ").
-- ══════════════════════════════════════════════════════════════════
-- update document_chunks set user_id = '<YOUR-USER-UUID>' where user_id is null;
--
-- insert into documents (user_id, filename, file_type, storage_key, page_count, chunks_count)
-- select user_id, filename, 'pdf', filename, max(page), count(*)
-- from document_chunks
-- where user_id = '<YOUR-USER-UUID>'
-- group by user_id, filename
-- on conflict (user_id, filename) do nothing;
