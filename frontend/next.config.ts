import type { NextConfig } from "next";

// Static export: FastAPI serves the built `out/` directory (one image, one origin).
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
};

export default nextConfig;
