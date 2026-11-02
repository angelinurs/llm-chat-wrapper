/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    // /api/* 요청을 FastAPI backend로 프록시
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;
