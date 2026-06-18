import test from 'node:test'
import assert from 'node:assert/strict'

import {
  createCsrfToken,
  createSignedSessionValue,
  parseAllowedUserEmails,
  parseCookieHeader,
  readSignedSessionValue,
} from './auth.mjs'

test('parseAllowedUserEmails normalizes and filters values', () => {
  const result = parseAllowedUserEmails(' Primary.User@example.com, ,Test@example.com ')

  assert.deepEqual([...result], ['primary.user@example.com', 'test@example.com'])
})

test('createSignedSessionValue round-trips a valid session', () => {
  const secret = 'session-secret'
  const session = {
    sub: 'google-subject',
    email: 'primary.user@example.com',
    exp: Math.floor(Date.now() / 1000) + 60,
  }

  const cookieValue = createSignedSessionValue(session, secret)
  const parsed = readSignedSessionValue(cookieValue, secret)

  assert.deepEqual(parsed, session)
})

test('readSignedSessionValue rejects tampered values', () => {
  const secret = 'session-secret'
  const session = {
    sub: 'google-subject',
    email: 'primary.user@example.com',
    exp: Math.floor(Date.now() / 1000) + 60,
  }

  const cookieValue = createSignedSessionValue(session, secret)
  const tampered = `${cookieValue.slice(0, -1)}x`

  assert.equal(readSignedSessionValue(tampered, secret), null)
})

test('readSignedSessionValue rejects expired sessions', () => {
  const secret = 'session-secret'
  const session = {
    sub: 'google-subject',
    email: 'primary.user@example.com',
    exp: Math.floor(Date.now() / 1000) - 1,
  }

  const cookieValue = createSignedSessionValue(session, secret)

  assert.equal(readSignedSessionValue(cookieValue, secret), null)
})

test('parseCookieHeader reads cookie pairs', () => {
  const cookies = parseCookieHeader('a=1; session=hello%20world; csrf=abc123')

  assert.deepEqual(cookies, {
    a: '1',
    session: 'hello world',
    csrf: 'abc123',
  })
})

test('createCsrfToken returns non-empty tokens', () => {
  const first = createCsrfToken()
  const second = createCsrfToken()

  assert.notEqual(first, second)
  assert.ok(first.length > 10)
})
