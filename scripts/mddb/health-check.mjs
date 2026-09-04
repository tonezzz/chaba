import http from 'node:http';

const PORT = process.env.PORT || 11435;
const HOST = process.env.HOST || 'localhost';

const req = http.get(`http://${HOST}:${PORT}/health`, (res) => {
  if (res.statusCode >= 200 && res.statusCode < 300) {
    process.exit(0);
  }
  console.error(`Health check returned status ${res.statusCode}`);
  process.exit(1);
});

req.on('error', (err) => {
  console.error(`Health check failed: ${err.message}`);
  process.exit(1);
});

req.setTimeout(3000, () => {
  console.error('Health check timed out');
  req.destroy();
  process.exit(1);
});
