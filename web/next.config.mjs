/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // ``standalone`` lets the Docker image ship ~40 MB instead of the full
  // node_modules. Cloud Run cold-start improves accordingly.
  output: "standalone",
  experimental: {
    typedRoutes: true,
  },
};

export default nextConfig;
