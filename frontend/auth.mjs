import crypto from 'node:crypto'

export function parseAllowedUserEmails(rawValue) {
  return new Set(
    String(rawValue || '')
      .split(',')
      .map((value) => value.trim().toLowerCase())
      .filter(Boolean),
  )
}

export function createCsrfToken() {
  return crypto.randomBytes(24).toString('base64url')
}

export function parseCookieHeader(cookieHeader) {
  const result = {}
  for (const part of String(cookieHeader || '').split(';')) {
    const trimmed = part.trim()
    if (!trimmed) {
      continue
    }
    const separatorIndex = trimmed.indexOf('=')
    if (separatorIndex <= 0) {
      continue
    }
    const key = trimmed.slice(0, separatorIndex).trim()
    const value = trimmed.slice(separatorIndex + 1).trim()
    result[key] = decodeURIComponent(value)
  }
  return result
}

function signPayload(payload, secret) {
  return crypto.createHmac('sha256', secret).update(payload).digest('base64url')
}

export function createSignedSessionValue(session, secret) {
  const payload = Buffer.from(JSON.stringify(session)).toString('base64url')
  const signature = signPayload(payload, secret)
  return `${payload}.${signature}`
}

export function readSignedSessionValue(cookieValue, secret) {
  if (!cookieValue || typeof cookieValue !== 'string') {
    return null
  }

  const separatorIndex = cookieValue.lastIndexOf('.')
  if (separatorIndex <= 0) {
    return null
  }

  const payload = cookieValue.slice(0, separatorIndex)
  const signature = cookieValue.slice(separatorIndex + 1)
  const expectedSignature = signPayload(payload, secret)
  const providedBuffer = Buffer.from(signature)
  const expectedBuffer = Buffer.from(expectedSignature)

  if (
    providedBuffer.length !== expectedBuffer.length ||
    !crypto.timingSafeEqual(providedBuffer, expectedBuffer)
  ) {
    return null
  }

  try {
    const session = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8'))
    if (!session || typeof session !== 'object') {
      return null
    }
    if (typeof session.exp !== 'number' || session.exp * 1000 <= Date.now()) {
      return null
    }
    return session
  } catch {
    return null
  }
}

export function createLoginPage({
  clientId,
  csrfToken,
  appTitle = 'Fynish',
  notice = 'Google sign-in is required to open this hosted workspace.',
}) {
  const escapedClientId = JSON.stringify(clientId)
  const escapedCsrfToken = JSON.stringify(csrfToken)
  const escapedAppTitle = JSON.stringify(appTitle)
  const escapedNotice = JSON.stringify(notice)

  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>${appTitle} sign-in</title>
    <script src="https://accounts.google.com/gsi/client" async defer></script>
    <style>
      :root {
        color-scheme: light;
        --ink: #241c18;
        --ink-soft: #6f655f;
        --paper: #fffaf5;
        --paper-soft: #f7efe7;
        --line: rgba(111, 101, 95, 0.18);
        --accent: #d86d45;
      }

      body {
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        padding: 24px;
        font-family: "Avenir Next", "Segoe UI", sans-serif;
        color: var(--ink);
        background:
          radial-gradient(circle at top left, rgba(244, 195, 147, 0.28), transparent 30%),
          radial-gradient(circle at top right, rgba(126, 169, 255, 0.18), transparent 28%),
          linear-gradient(180deg, var(--paper) 0%, var(--paper-soft) 100%);
      }

      .card {
        width: min(520px, calc(100vw - 32px));
        display: grid;
        gap: 16px;
        padding: 28px;
        border-radius: 28px;
        border: 1px solid var(--line);
        background: rgba(255, 252, 247, 0.92);
        box-shadow: 0 24px 50px rgba(35, 29, 24, 0.07);
        backdrop-filter: blur(14px);
      }

      .eyebrow {
        font-size: 0.82rem;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: var(--ink-soft);
      }

      h1 {
        margin: 0;
        font-size: clamp(2.2rem, 7vw, 3.6rem);
        line-height: 0.95;
      }

      p {
        margin: 0;
        color: var(--ink-soft);
        font-size: 1.02rem;
      }

      #signin-status {
        min-height: 1.5em;
        color: var(--accent);
        font-size: 0.95rem;
      }

      #google-signin {
        min-height: 48px;
      }
    </style>
  </head>
  <body>
    <main class="card">
      <div class="eyebrow">Private hosted workspace</div>
      <h1>${appTitle}</h1>
      <p>${notice}</p>
      <div id="google-signin"></div>
      <div id="signin-status" role="status" aria-live="polite"></div>
    </main>

    <script>
      const clientId = ${escapedClientId};
      const csrfToken = ${escapedCsrfToken};
      const statusEl = document.getElementById('signin-status');

      function setStatus(message) {
        statusEl.textContent = message || '';
      }

      async function handleCredentialResponse(response) {
        setStatus('Signing you in...');
        try {
          const authResponse = await fetch('/auth/google', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            credentials: 'same-origin',
            body: JSON.stringify({
              credential: response.credential,
              csrf_token: csrfToken,
            }),
          });

          const payload = await authResponse.json().catch(() => ({}));
          if (!authResponse.ok) {
            setStatus(payload.error || 'Unable to sign in with Google.');
            return;
          }

          window.location.assign('/');
        } catch (error) {
          setStatus('Unable to sign in with Google.');
        }
      }

      window.addEventListener('load', () => {
        google.accounts.id.initialize({
          client_id: clientId,
          callback: handleCredentialResponse,
          auto_select: false,
          ux_mode: 'popup',
        });

        google.accounts.id.renderButton(
          document.getElementById('google-signin'),
          {
            theme: 'outline',
            size: 'large',
            text: 'signin_with',
            shape: 'pill',
            width: 280,
          },
        );
      });
    </script>
  </body>
</html>`
}

export function createConfigErrorPage(message) {
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Fynish auth configuration</title>
    <style>
      body {
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        padding: 24px;
        font-family: "Avenir Next", "Segoe UI", sans-serif;
        background: #faf4ee;
        color: #241c18;
      }

      main {
        width: min(640px, calc(100vw - 32px));
        padding: 28px;
        border-radius: 24px;
        border: 1px solid rgba(111, 101, 95, 0.18);
        background: white;
      }

      h1 {
        margin-top: 0;
      }
    </style>
  </head>
  <body>
    <main>
      <h1>Frontend auth is enabled, but not fully configured.</h1>
      <p>${message}</p>
    </main>
  </body>
</html>`
}
