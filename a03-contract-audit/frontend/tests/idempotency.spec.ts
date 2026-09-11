import { expect, test } from '@playwright/test'

import {
  createAuditIdempotencyKey,
  createUploadIdempotencyKey,
} from '../src/utils/idempotency'


test('upload idempotency key is stable for identical content', async () => {
  const first = await createUploadIdempotencyKey(new Blob(['same contract']))
  const repeated = await createUploadIdempotencyKey(new Blob(['same contract']))
  const different = await createUploadIdempotencyKey(new Blob(['different contract']))

  expect(first).toBe(repeated)
  expect(first).toMatch(/^upload:[a-f0-9]{64}$/)
  expect(different).not.toBe(first)
})

test('audit idempotency key is stable within one action and changes for a new action', async () => {
  const first = await createAuditIdempotencyKey('operation-1')
  const repeated = await createAuditIdempotencyKey('operation-1')
  const nextAction = await createAuditIdempotencyKey('operation-2')

  expect(first).toBe(repeated)
  expect(first).toMatch(/^audit:[a-f0-9]{64}$/)
  expect(nextAction).not.toBe(first)
})
