async function sha256Hex(input: ArrayBuffer | string): Promise<string> {
  const bytes = typeof input === 'string'
    ? new TextEncoder().encode(input)
    : new Uint8Array(input)
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

export async function createUploadIdempotencyKey(file: Blob): Promise<string> {
  return `upload:${await sha256Hex(await file.arrayBuffer())}`
}

export async function createAuditIdempotencyKey(
  operationId = crypto.randomUUID(),
): Promise<string> {
  return `audit:${await sha256Hex(operationId)}`
}
