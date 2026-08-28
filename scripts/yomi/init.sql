CREATE TABLE IF NOT EXISTS conversations (
    chat_id TEXT PRIMARY KEY,
    name TEXT,
    is_group BOOLEAN NOT NULL DEFAULT false,
    category TEXT,
    category_source TEXT,
    unread INTEGER NOT NULL DEFAULT 0,
    last_message_time BIGINT,
    last_preview TEXT,
    summary TEXT,
    meta JSONB,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL REFERENCES conversations(chat_id) ON DELETE CASCADE,
    from_name TEXT,
    delivered_time BIGINT,
    text TEXT,
    media_type TEXT,
    media_path TEXT,
    e2ee JSONB,
    data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS messages_chat_id_time ON messages(chat_id, delivered_time DESC);
CREATE INDEX IF NOT EXISTS conv_last_time ON conversations(last_message_time DESC);

CREATE TABLE IF NOT EXISTS overrides (
    chat_id TEXT PRIMARY KEY REFERENCES conversations(chat_id) ON DELETE CASCADE,
    category TEXT,
    is_group BOOLEAN,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS daily_summaries (
    id SERIAL PRIMARY KEY,
    chat_id TEXT NOT NULL REFERENCES conversations(chat_id) ON DELETE CASCADE,
    date DATE NOT NULL,
    events TEXT[],
    actions TEXT[],
    topics TEXT[],
    summary TEXT,
    message_count INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(chat_id, date)
);

CREATE INDEX IF NOT EXISTS daily_summaries_chat_date ON daily_summaries(chat_id, date DESC);

CREATE TABLE IF NOT EXISTS media_analysis_jobs (
    id SERIAL PRIMARY KEY,
    chat_id TEXT NOT NULL REFERENCES conversations(chat_id) ON DELETE CASCADE,
    message_id TEXT NOT NULL REFERENCES messages(message_id) ON DELETE CASCADE,
    media_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    analysis_result TEXT,
    model_used TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    tokens_used INTEGER,
    cost_usd NUMERIC(10, 6),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS media_analysis_jobs_chat_id ON media_analysis_jobs(chat_id);
CREATE INDEX IF NOT EXISTS media_analysis_jobs_status ON media_analysis_jobs(status);
CREATE INDEX IF NOT EXISTS media_analysis_jobs_created_at ON media_analysis_jobs(created_at DESC);

-- Add analysis_result column to messages table for storing cached media analysis
ALTER TABLE messages ADD COLUMN IF NOT EXISTS media_analysis TEXT;

