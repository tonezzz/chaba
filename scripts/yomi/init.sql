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

