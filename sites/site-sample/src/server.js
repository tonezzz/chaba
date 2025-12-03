import path from 'path';
import express from 'express';
import morgan from 'morgan';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = process.env.PORT || 3000;

app.use(morgan('dev'));
app.use(express.json());
app.use(express.static(path.join(__dirname, '..', 'public')));

app.get('/api/health', (req, res) => {
  res.json({ status: 'ok', node: process.version, timestamp: new Date().toISOString() });
});

app.get('/api/greeting', (req, res) => {
  const name = req.query.name || 'friend';
  res.json({ message: `Hello, ${name}! Welcome to node-1 sample site.` });
});

app.use((req, res, next) => {
  res.status(404).sendFile(path.join(__dirname, '..', 'public', '404.html'));
});

app.use((err, req, res, next) => {
  console.error(err);
  res.status(500).json({ error: 'Internal Server Error' });
});

app.listen(PORT, () => {
  console.log(`Sample site listening on port ${PORT}`);
});
