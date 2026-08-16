import path from 'node:path'
import type { NextConfig } from 'next'

export function localRuntimeRewritesEnabled(
  optIn: string | undefined,
  backendUrl: string | undefined,
  nodeEnv: string | undefined,
): boolean {
  if (optIn !== '1' || nodeEnv === 'production' || !backendUrl) {
    return false
  }
  try {
    const hostname = new URL(backendUrl).hostname
    return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]'
  } catch {
    return false
  }
}

const nextConfig: NextConfig = {
  // Enable React strict mode
  reactStrictMode: true,
  turbopack: {
    root: path.resolve(__dirname, '..'),
  },

  // Optimize images
  images: {
    unoptimized: true,
  },

  async rewrites() {
    const backendUrl = process.env.AGENT_BACKEND_URL?.replace(/\/$/, '')
    if (!backendUrl) {
      return []
    }

    const stableRewrites = [
      {
        source: '/api/get_config',
        destination: `${backendUrl}/get_config`,
      },
      {
        source: '/api/startAgent',
        destination: `${backendUrl}/startAgent`,
      },
      {
        source: '/api/stopAgent',
        destination: `${backendUrl}/stopAgent`,
      },
    ]
    if (!localRuntimeRewritesEnabled(process.env.VOICE_ACP_LOCAL_RUNTIME, backendUrl, process.env.NODE_ENV)) {
      return stableRewrites
    }

    return [
      ...stableRewrites,
      {
        source: '/api/local/workspace',
        destination: `${backendUrl}/local/workspace`,
      },
      {
        source: '/api/local/workspace/browse',
        destination: `${backendUrl}/local/workspace/browse`,
      },
      {
        source: '/api/local/workspace/browse/:operationId',
        destination: `${backendUrl}/local/workspace/browse/:operationId`,
      },
      {
        source: '/api/local/runtime',
        destination: `${backendUrl}/local/runtime`,
      },
    ]
  },
}

export default nextConfig
