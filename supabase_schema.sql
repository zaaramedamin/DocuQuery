-- Enable the pgvector extension to work with embedding vectors
create extension if not exists vector;

-- Create the table to store document chunks and their vector embeddings
create table if not exists document_chunks (
  id bigserial primary key,
  filename text not null,
  chunk_index integer not null,
  text text not null,
  page integer not null,
  embedding vector(384) not null  -- 384 dimensions for sentence-transformers/all-MiniLM-L6-v2
);

-- Create a spatial vector index for HNSW similarity search
create index if not exists document_chunks_embedding_hnsw_idx 
on document_chunks 
using hnsw (embedding vector_cosine_ops);

-- Create a database function to match documents using cosine similarity
create or replace function match_documents (
  query_embedding vector(384),
  match_threshold float,
  match_count int,
  filter_filename text default null
)
returns table (
  id bigint,
  filename text,
  chunk_index int,
  text text,
  page int,
  similarity float
)
language plpgsql
as $$
begin
  return query
  select
    document_chunks.id,
    document_chunks.filename,
    document_chunks.chunk_index,
    document_chunks.text,
    document_chunks.page,
    1 - (document_chunks.embedding <=> query_embedding) as similarity
  from document_chunks
  where (filter_filename is null or document_chunks.filename = filter_filename)
    and 1 - (document_chunks.embedding <=> query_embedding) > match_threshold
  order by document_chunks.embedding <=> query_embedding
  limit match_count;
end;
$$;

-- Efficient DISTINCT filename listing (avoids fetching one row per chunk)
create or replace function list_document_filenames()
returns setof text
language sql
as $$
  select distinct filename from document_chunks;
$$;

-- ══════════════════════════════════════════════════════════════════
-- Storage bucket for the original PDF files
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
