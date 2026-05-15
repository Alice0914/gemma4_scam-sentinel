import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next.js 16 blocks dev-resource requests from origins other than the one
  // the dev server was started with. We access the app from both localhost and
  // 127.0.0.1, so allow both — otherwise the React bundle never hydrates and
  // onClick handlers stay unattached (channel tabs won't switch, Analyze
  // button does nothing).
  allowedDevOrigins: ["127.0.0.1", "localhost"],
};

export default nextConfig;
