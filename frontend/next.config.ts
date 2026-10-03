import type { NextConfig } from "next";
const config: NextConfig = {
  output: process.env.NEXT_STANDALONE === "true" ? "standalone" : undefined,
  poweredByHeader: false,
};
export default config;
