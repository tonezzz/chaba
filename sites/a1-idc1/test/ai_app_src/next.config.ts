import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  basePath: "/test/ai_app",
  output: "export",
  images: {
    unoptimized: true,
  },
  reactCompiler: true,
};

export default nextConfig;
