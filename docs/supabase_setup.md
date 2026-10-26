# RxShield — Supabase Database & Authentication Setup

## Architecture & Privacy-First Design

RxShield supports optional cloud persistence using **Supabase** (PostgreSQL + GoTrue Auth).

### Strict Privacy Principles
1. **Zero Health PII Storage**: RxShield **never** stores patient names, ages, diagnoses, medical conditions, or allergy notes in the database.
2. **Only Medication Identifiers**: Saved regimens contain only an optional user-chosen label (e.g. "Morning Routine") and an array of standardized RxNorm medication IDs (e.g. `['rxnorm:drug:202433', 'rxnorm:drug:153010']`).
3. **Public Anon Key Only**: The frontend application strictly utilizes the public `SUPABASE_ANON_KEY`. The privileged `service_role` key is **never** used or exposed.
4. **Row Level Security (RLS)**: Enforced directly at the PostgreSQL layer so users can only view, insert, or delete their own saved records.
5. **Optional / Anonymous Usage**: RxShield operates in full anonymous guest mode when unconfigured. Users are never forced to register to run safety checks, graph searches, or reports.

---

## 1. Supabase Project Configuration

1. Create a project at [https://supabase.com](https://supabase.com).
2. Go to **Project Settings** → **API**.
3. Copy:
   - **Project URL** (`https://<project-id>.supabase.co`)
   - **anon public key** (`eyJhbGciOi...`)

---

## 2. PostgreSQL DDL & Row Level Security Schema

Execute the following SQL in your Supabase project's **SQL Editor**:

```sql
-- Create table for user-saved medication regimens
create table public.user_saved_regimens (
    id uuid default gen_random_uuid() primary key,
    user_id uuid references auth.users(id) on delete cascade not null,
    name text not null check (char_length(name) <= 100),
    medication_ids text[] not null,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

-- Enable Row Level Security (RLS)
alter table public.user_saved_regimens enable row level security;

-- Policy: Users can only select their own regimens
create policy "Users can view their own regimens"
    on public.user_saved_regimens for select
    using (auth.uid() = user_id);

-- Policy: Users can only insert regimens under their own user_id
create policy "Users can create their own regimens"
    on public.user_saved_regimens for insert
    with check (auth.uid() = user_id);

-- Policy: Users can only delete their own regimens
create policy "Users can delete their own regimens"
    on public.user_saved_regimens for delete
    using (auth.uid() = user_id);
```

---

## 3. Application Configuration

Add your keys to `.env` or `.streamlit/secrets.toml`:

### In `.env`:
```bash
SUPABASE_URL="https://<project-id>.supabase.co"
SUPABASE_ANON_KEY="eyJhbGciOi..."
```

### Or in `.streamlit/secrets.toml`:
```toml
SUPABASE_URL = "https://<project-id>.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOi..."
```

If these keys are omitted, RxShield operates gracefully in anonymous mode without warning messages.
