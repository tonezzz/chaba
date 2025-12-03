# node-1 Logger Demo

Express service that writes structured logs (console + rotating files) so you can test how Plesk surfaces log output.

## Endpoints

- `GET /api/health` – quick status check
- `GET /api/log-demo` – generates a WARN log with request metadata
- `POST /api/events` – accept JSON and log it with INFO level
- `GET /api/logs` – returns the tail (100 lines) of `logs/app.log`

## Local dev

```bash
npm install
npm run dev
```

## Production start

```
npm install --production
npm run start
```

Set `app.js` as the startup file in Plesk. Logs are written under `logs/` (ensure writable permissions). Use Plesk’s “Logs” tab to view output or tail the files via SSH.
