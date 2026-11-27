/** @type {import('next').NextConfig} */
const nextConfig = {
  // The browser end-to-end test builds into its own folder so it never fights a dev server running here.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  /* config options here */
  cacheComponents: true,
  partialPrefetching: true,
};

export default nextConfig;
