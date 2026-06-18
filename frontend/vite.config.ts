import { execFileSync } from 'node:child_process'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

type IdentityTokenCache = {
  expiresAt: number
  token: string
}

let cachedIdentityToken: IdentityTokenCache | null = null
let cachedGcloudAccountEmail: string | null | undefined

function getCloudRunIdentityToken() {
  const now = Date.now()
  if (cachedIdentityToken && cachedIdentityToken.expiresAt > now + 5 * 60 * 1000) {
    return cachedIdentityToken.token
  }

  const token = execFileSync('gcloud', ['auth', 'print-identity-token'], {
    encoding: 'utf-8',
  }).trim()

  cachedIdentityToken = {
    token,
    expiresAt: now + 50 * 60 * 1000,
  }
  return token
}

function getGcloudAccountEmail() {
  if (cachedGcloudAccountEmail !== undefined) {
    return cachedGcloudAccountEmail
  }

  try {
    const email = execFileSync('gcloud', ['config', 'get-value', 'account'], {
      encoding: 'utf-8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim()
    cachedGcloudAccountEmail = email && email !== '(unset)' ? email : null
  } catch {
    cachedGcloudAccountEmail = null
  }

  return cachedGcloudAccountEmail
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const cloudRunProxyUrl = (
    env.FYNISH_CLOUD_RUN_PROXY_URL ||
    env.VITE_CLOUD_RUN_PROXY_URL ||
    process.env.FYNISH_CLOUD_RUN_PROXY_URL ||
    process.env.VITE_CLOUD_RUN_PROXY_URL ||
    ''
  ).trim()
  const proxyAuthenticatedEmail = (
    env.FYNISH_PROXY_AUTHENTICATED_EMAIL ||
    env.VITE_PROXY_AUTHENTICATED_EMAIL ||
    process.env.FYNISH_PROXY_AUTHENTICATED_EMAIL ||
    process.env.VITE_PROXY_AUTHENTICATED_EMAIL ||
    getGcloudAccountEmail() ||
    ''
  ).trim()
  const proxyAuthenticatedName = (
    env.FYNISH_PROXY_AUTHENTICATED_NAME ||
    env.VITE_PROXY_AUTHENTICATED_NAME ||
    process.env.FYNISH_PROXY_AUTHENTICATED_NAME ||
    process.env.VITE_PROXY_AUTHENTICATED_NAME ||
    proxyAuthenticatedEmail
  ).trim()

  return {
    plugins: [react()],
    server: cloudRunProxyUrl
      ? {
          proxy: {
            '/api': {
              target: cloudRunProxyUrl,
              changeOrigin: true,
              secure: true,
              configure(proxy) {
                proxy.on('proxyReq', (proxyReq) => {
                  proxyReq.setHeader('Authorization', `Bearer ${getCloudRunIdentityToken()}`)
                  if (proxyAuthenticatedEmail) {
                    proxyReq.setHeader(
                      'X-Fynish-Authenticated-Email',
                      proxyAuthenticatedEmail,
                    )
                    proxyReq.setHeader(
                      'X-Fynish-Authenticated-Name',
                      proxyAuthenticatedName || proxyAuthenticatedEmail,
                    )
                  }
                })
              },
            },
          },
        }
      : undefined,
  }
})
