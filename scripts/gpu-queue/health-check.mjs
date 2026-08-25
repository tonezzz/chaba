import http from 'node:http';

const PORT = process.env.GPU_QUEUE_PORT || 3001;

const req = http.get(`http://127.0.0.1:${PORT}/health`, (res) => {
  res.resume();
  process.exit(res.statusCode === 200 ? 0 : 1);
});

req.on('error', () => process.exit(1));
