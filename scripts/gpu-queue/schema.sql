-- GPU Queue Jobs Table
CREATE TABLE IF NOT EXISTS gpu_queue_jobs (
  id SERIAL PRIMARY KEY,
  type VARCHAR(50) NOT NULL, -- llama, imagen2, cogvideo
  params JSONB NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending, running, completed, failed, cancelled
  priority INTEGER NOT NULL, -- 3=cogvideo, 2=imagen2, 1=llama
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  started_at TIMESTAMP WITH TIME ZONE,
  completed_at TIMESTAMP WITH TIME ZONE,
  error TEXT
);

-- Index for status queries
CREATE INDEX IF NOT EXISTS idx_gpu_queue_jobs_status ON gpu_queue_jobs(status);

-- Index for priority ordering within pending jobs
CREATE INDEX IF NOT EXISTS idx_gpu_queue_jobs_priority ON gpu_queue_jobs(priority) WHERE status = 'pending';

-- Index for created_at ordering
CREATE INDEX IF NOT EXISTS idx_gpu_queue_jobs_created ON gpu_queue_jobs(created_at DESC);
