import fs from 'fs';
import { promises as fsPromises } from 'fs';
import path from 'path';
import express from 'express';
import morgan from 'morgan';
import winston from 'winston';
import DailyRotateFile from 'winston-daily-rotate-file';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = process.env.PORT || 3100;
const logsDir = path.join(__dirname, '..', 'logs');
const latestLog = path.join(logsDir, 'app.log');

fs.mkdirSync(logsDir, { recursive: true });

const logger = winston.createLogger({
  level: process.env.LOG_LEVEL || 'info',
  format: winston.format.combine(
    winston.format.timestamp(),
    winston.format.printf(({ timestamp, level, message, ...meta }) =>
      `${timestamp} ${level}: ${message}${Object.keys(meta).length ? ` ${JSON.stringify(meta)}` : ''}`
    )
  ),
  transports: [
    new winston.transports.Console({ handleExceptions: true }),
    new winston.transports.File({ filename: latestLog }),
    new DailyRotateFile({
      dirname: logsDir,
      filename: 'app-%DATE%.log',
      datePattern: 'YYYY-MM-DD',
      maxFiles: '14d'
    })
  ]
});

app.use(express.json());
app.use(
  morgan('combined', {
    stream: {
      write: (message) => logger.http?.(message.trim()) || logger.info(message.trim(), { channel: 'http' })
    }
  })
);
app.use(express.static(path.join(__dirname, '..', 'public')));

app.get('/api/health', (req, res) => {
  res.json({ status: 'ok', uptime: process.uptime(), logFile: latestLog });
});

app.post('/api/events', (req, res) => {
  const payload = req.body || {};
  logger.info('Custom event received', {
    ip: req.ip,
    userAgent: req.headers['user-agent'],
    payload
  });
  res.status(201).json({ ok: true });
});

app.get('/api/log-demo', (req, res) => {
  const sample = {
    ip: req.ip,
    userAgent: req.headers['user-agent'],
    requestId: Math.random().toString(36).slice(2, 10)
  };
  logger.warn('Manual log trigger', sample);
  res.json({ message: 'Event logged. Check logs!' });
});

app.get('/api/logs', async (req, res) => {
  try {
    const data = await fsPromises.readFile(latestLog, 'utf8');
    const lines = data.trim().split('\n');
    res.json({ lines: lines.slice(-100) });
  } catch (error) {
    if (error.code === 'ENOENT') {
      res.json({ lines: [], note: 'No logs yet' });
      return;
    }
    res.status(500).json({ error: 'Unable to read logs', details: error.message });
  }
});

app.use((req, res) => {
  res.status(404).json({ error: 'Not Found' });
});

app.listen(PORT, () => {
  logger.info(`Logger sample listening on ${PORT}`);
});
