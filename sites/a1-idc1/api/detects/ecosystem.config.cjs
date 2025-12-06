module.exports = {
  apps: [
    {
      name: 'detects-api',
      script: 'src/server.js',
      interpreter: 'node',
      node_args: '-r dotenv/config',
      cwd: __dirname,
      watch: ['src'],
      ignore_watch: ['node_modules', 'logs'],
      env: {
        NODE_ENV: 'development',
        PORT: process.env.PORT || '4120'
      },
      env_production: {
        NODE_ENV: 'production',
        PORT: process.env.PORT || '4120'
      }
    }
  ]
};
