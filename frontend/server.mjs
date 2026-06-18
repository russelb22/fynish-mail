import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import express from 'express'
import { OAuth2Client } from 'google-auth-library'

import {
  createConfigErrorPage,
  createCsrfToken,
  createLoginPage,
  createSignedSessionValue,
  parseAllowedUserEmails,
  parseCookieHeader,
  readSignedSessionValue,
} from './auth.mjs'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const distDir = path.join(__dirname, 'dist')
const indexPath = path.join(distDir, 'index.html')

const backendUrl = (process.env.FYNISH_BACKEND_URL || '').trim()
if (!backendUrl) {
  throw new Error('FYNISH_BACKEND_URL is required for the hosted frontend proxy.')
}

const port = Number.parseInt(process.env.PORT || '8080', 10)
const authEnabled = ['1', 'true', 'yes', 'on'].includes(
  String(process.env.FYNISH_AUTH_ENABLED || '0').trim().toLowerCase(),
)
const googleAuthClientId = String(process.env.FYNISH_GOOGLE_AUTH_CLIENT_ID || '').trim()
const sessionSecret = String(process.env.FYNISH_SESSION_SECRET || '').trim()
const allowedUserEmails = parseAllowedUserEmails(process.env.FYNISH_ALLOWED_USER_EMAILS || '')
const sessionTtlSeconds = Number.parseInt(
  process.env.FYNISH_SESSION_TTL_SECONDS || '43200',
  10,
)
const SESSION_COOKIE_NAME = 'fynish-auth-session'
const CSRF_COOKIE_NAME = 'fynish-auth-csrf'
const googleAuthClient = googleAuthClientId ? new OAuth2Client(googleAuthClientId) : null
let cachedBackendIdentityToken = null
let cachedBackendIdentityTokenExpiresAt = 0

function decodeJwtPayload(token) {
  const payload = token.split('.')[1]
  return JSON.parse(Buffer.from(payload, 'base64url').toString('utf8'))
}

async function getBackendIdentityToken() {
  const now = Date.now()
  if (cachedBackendIdentityToken && cachedBackendIdentityTokenExpiresAt > now + 60_000) {
    return cachedBackendIdentityToken
  }

  const tokenResponse = await fetch(
    `http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity?audience=${encodeURIComponent(
      backendUrl,
    )}&format=full`,
    {
      headers: {
        'Metadata-Flavor': 'Google',
      },
    },
  )

  if (!tokenResponse.ok) {
    throw new Error(`Unable to fetch backend identity token: ${tokenResponse.status}`)
  }

  const token = await tokenResponse.text()
  const payload = decodeJwtPayload(token)
  cachedBackendIdentityToken = token
  cachedBackendIdentityTokenExpiresAt = Number(payload.exp || 0) * 1000
  return token
}

const app = express()
app.set('trust proxy', 1)

function requestIsSecure(req) {
  const forwardedProto = req.get('x-forwarded-proto')
  return req.secure || forwardedProto === 'https'
}

function getSessionUser(req) {
  if (!authEnabled || !sessionSecret) {
    return null
  }
  const cookies = parseCookieHeader(req.headers.cookie)
  return readSignedSessionValue(cookies[SESSION_COOKIE_NAME], sessionSecret)
}

function clearAuthCookies(req, res) {
  const secure = requestIsSecure(req)
  const cookieOptions = {
    httpOnly: true,
    secure,
    sameSite: 'lax',
    path: '/',
  }
  res.clearCookie(SESSION_COOKIE_NAME, cookieOptions)
  res.clearCookie(CSRF_COOKIE_NAME, {
    ...cookieOptions,
    httpOnly: false,
  })
}

function authConfigError() {
  if (!authEnabled) {
    return null
  }
  if (!googleAuthClientId) {
    return 'FYNISH_GOOGLE_AUTH_CLIENT_ID is required.'
  }
  if (!sessionSecret) {
    return 'FYNISH_SESSION_SECRET is required.'
  }
  if (allowedUserEmails.size === 0) {
    return 'FYNISH_ALLOWED_USER_EMAILS must include at least one approved email address.'
  }
  return null
}

function appendQueryParams(targetUrl, params) {
  const isAbsolute = /^https?:\/\//i.test(targetUrl)
  const url = new URL(targetUrl, 'http://localhost')
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') {
      continue
    }
    url.searchParams.set(key, String(value))
  }
  if (isAbsolute) {
    return url.toString()
  }
  return `${url.pathname}${url.search}${url.hash}`
}

function buildBackendProxyHeaders(req, identityToken) {
  const headers = new Headers()

  for (const [key, value] of Object.entries(req.headers)) {
    if (value === undefined) {
      continue
    }
    const lowerKey = key.toLowerCase()
    if (lowerKey === 'host' || lowerKey === 'content-length') {
      continue
    }
    if (Array.isArray(value)) {
      headers.set(key, value.join(', '))
    } else {
      headers.set(key, value)
    }
  }

  headers.set('Authorization', `Bearer ${identityToken}`)
  if (req.fynishUser?.email) {
    headers.set('X-Fynish-Authenticated-Email', req.fynishUser.email)
    headers.set('X-Fynish-Authenticated-Name', req.fynishUser.name || req.fynishUser.email)
  }
  if (req.fynishUser?.sub) {
    headers.set('X-Fynish-Authenticated-Sub', req.fynishUser.sub)
  }

  return headers
}

app.use((req, res, next) => {
  req.fynishUser = getSessionUser(req)
  next()
})

app.get('/auth/me', (req, res) => {
  res.json({
    auth_enabled: authEnabled,
    user: req.fynishUser
      ? {
          email: req.fynishUser.email,
          name: req.fynishUser.name || req.fynishUser.email,
          picture: req.fynishUser.picture || null,
        }
      : null,
  })
})

app.get('/auth/login', (req, res) => {
  if (!authEnabled) {
    res.redirect('/')
    return
  }

  if (req.fynishUser) {
    res.redirect('/')
    return
  }

  const configError = authConfigError()
  res.setHeader('Content-Type', 'text/html; charset=utf-8')
  if (configError) {
    res.status(500).send(createConfigErrorPage(configError))
    return
  }

  const cookies = parseCookieHeader(req.headers.cookie)
  const csrfToken = cookies[CSRF_COOKIE_NAME] || createCsrfToken()
  res.cookie(CSRF_COOKIE_NAME, csrfToken, {
    httpOnly: false,
    secure: requestIsSecure(req),
    sameSite: 'lax',
    path: '/',
    maxAge: 10 * 60 * 1000,
  })
  res.send(
    createLoginPage({
      clientId: googleAuthClientId,
      csrfToken,
      appTitle: 'Fynish',
      notice: 'Sign in with Google to open your private Fynish workspace.',
    }),
  )
})

app.post('/auth/google', express.json({ limit: '64kb' }), async (req, res) => {
  if (!authEnabled) {
    res.status(404).json({ error: 'Hosted frontend auth is disabled.' })
    return
  }

  const configError = authConfigError()
  if (configError) {
    res.status(500).json({ error: configError })
    return
  }

  const cookies = parseCookieHeader(req.headers.cookie)
  const cookieCsrfToken = cookies[CSRF_COOKIE_NAME]
  const bodyCsrfToken = String(req.body?.csrf_token || '')
  const credential = String(req.body?.credential || '')

  if (!cookieCsrfToken || !bodyCsrfToken || cookieCsrfToken !== bodyCsrfToken) {
    res.status(400).json({ error: 'Sign-in request could not be verified.' })
    return
  }

  if (!credential) {
    res.status(400).json({ error: 'Missing Google credential.' })
    return
  }

  try {
    const ticket = await googleAuthClient.verifyIdToken({
      idToken: credential,
      audience: googleAuthClientId,
    })
    const payload = ticket.getPayload()
    const email = String(payload?.email || '').trim().toLowerCase()

    if (!payload?.sub || !email || payload.email_verified !== true) {
      res.status(403).json({ error: 'Google identity could not be verified.' })
      return
    }

    if (!allowedUserEmails.has(email)) {
      res.status(403).json({ error: `Access is not enabled for ${email}.` })
      return
    }

    const session = {
      sub: payload.sub,
      email,
      name: payload.name || email,
      picture: payload.picture || null,
      exp: Math.floor(Date.now() / 1000) + sessionTtlSeconds,
    }

    res.cookie(SESSION_COOKIE_NAME, createSignedSessionValue(session, sessionSecret), {
      httpOnly: true,
      secure: requestIsSecure(req),
      sameSite: 'lax',
      path: '/',
      maxAge: sessionTtlSeconds * 1000,
    })
    res.clearCookie(CSRF_COOKIE_NAME, {
      httpOnly: false,
      secure: requestIsSecure(req),
      sameSite: 'lax',
      path: '/',
    })
    res.json({
      user: {
        email: session.email,
        name: session.name,
        picture: session.picture,
      },
    })
  } catch (error) {
    console.error('Google sign-in verification failed', error)
    res.status(401).json({ error: 'Google sign-in could not be verified.' })
  }
})

app.post('/auth/logout', (req, res) => {
  clearAuthCookies(req, res)
  res.json({ logged_out: true })
})

app.get('/auth/gmail/callback', async (req, res) => {
  if (authEnabled && !req.fynishUser) {
    res.redirect('/auth/login')
    return
  }

  try {
    const identityToken = await getBackendIdentityToken()
    const headers = buildBackendProxyHeaders(req, identityToken)
    const callbackQuery = new URLSearchParams(req.query).toString()
    const response = await fetch(
      `${backendUrl}/api/accounts/connect-gmail/callback${callbackQuery ? `?${callbackQuery}` : ''}`,
      {
        method: 'GET',
        headers,
      },
    )

    const payload = await response.json().catch(() => ({}))
    if (!response.ok) {
      const detail =
        typeof payload?.detail === 'string'
          ? payload.detail
          : 'Gmail connection could not be completed.'
      const code = typeof payload?.code === 'string' ? payload.code : undefined
      res.redirect(
        appendQueryParams('/', {
          view: 'accounts',
          gmail_connect: 'error',
          gmail_message: detail,
          gmail_code: code,
        }),
      )
      return
    }

    res.redirect(
      payload?.redirect_url ||
        appendQueryParams('/', {
          view: 'accounts',
          gmail_connect: 'success',
          gmail_message: 'Gmail account connected.',
        }),
    )
  } catch (error) {
    console.error('Hosted Gmail callback proxy failed', error)
    res.redirect(
      appendQueryParams('/', {
        view: 'accounts',
        gmail_connect: 'error',
        gmail_message: 'Hosted Gmail callback proxy failed.',
      }),
    )
  }
})

app.use((req, res, next) => {
  if (!authEnabled) {
    next()
    return
  }

  const configError = authConfigError()
  if (configError) {
    if (req.path.startsWith('/auth')) {
      next()
      return
    }
    if (req.path.startsWith('/api')) {
      res.status(503).json({ error: configError })
      return
    }
    res.redirect('/auth/login')
    return
  }

  if (req.path.startsWith('/auth')) {
    next()
    return
  }

  if (!req.fynishUser) {
    if (req.path.startsWith('/api')) {
      res.status(401).json({ error: 'Sign-in required.' })
      return
    }
    if (req.path.startsWith('/assets/')) {
      res.status(404).end()
      return
    }
    if (req.method === 'GET' || req.method === 'HEAD') {
      res.redirect('/auth/login')
      return
    }
    res.status(401).json({ error: 'Sign-in required.' })
    return
  }

  next()
})

app.use('/api', express.raw({ type: '*/*', limit: '5mb' }))

app.use('/api', async (req, res) => {
  try {
    const identityToken = await getBackendIdentityToken()
    const headers = buildBackendProxyHeaders(req, identityToken)

    const response = await fetch(`${backendUrl}${req.originalUrl}`, {
      method: req.method,
      headers,
      body:
        req.method === 'GET' || req.method === 'HEAD' || req.body.length === 0
          ? undefined
          : req.body,
      redirect: 'manual',
    })

    if (response.status === 401 || response.status === 403) {
      console.error('API proxy auth rejection', {
        method: req.method,
        path: req.originalUrl,
        status: response.status,
      })
    }

    res.status(response.status)
    response.headers.forEach((value, key) => {
      const lowerKey = key.toLowerCase()
      if (lowerKey === 'content-encoding' || lowerKey === 'transfer-encoding') {
        return
      }
      res.setHeader(key, value)
    })

    const body = Buffer.from(await response.arrayBuffer())
    res.send(body)
  } catch (error) {
    console.error('API proxy failed', error)
    res.status(502).json({ error: 'Hosted frontend proxy failed.' })
  }
})

app.use(express.static(distDir, { index: false }))

app.use((req, res, next) => {
  if (req.path.startsWith('/api')) {
    next()
    return
  }
  res.setHeader('Content-Type', 'text/html; charset=utf-8')
  res.send(fs.readFileSync(indexPath, 'utf-8'))
})

app.listen(port, () => {
  console.log(`Fynish frontend listening on port ${port}`)
})
