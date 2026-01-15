const { i18n } = require('./next-i18next.config');

const basePath = (process.env.NEXT_PUBLIC_BASE_PATH || '').trim();

/** @type {import('next').NextConfig} */
const nextConfig = {
  i18n,
  reactStrictMode: true,

  ...(basePath
    ? {
        basePath,
        assetPrefix: basePath,
      }
    : {}),

  webpack(config, { isServer, dev }) {
    config.experiments = {
      asyncWebAssembly: true,
      layers: true,
    };

    return config;
  },
};

module.exports = nextConfig;
