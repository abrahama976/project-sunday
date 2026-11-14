import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Required for local and Tailscale development origins; Next otherwise
  // blocks cross-origin dev assets and prevents hydration.
  allowedDevOrigins: ["localhost", "127.0.0.1", "*.ts.net"],
};

export default nextConfig;
