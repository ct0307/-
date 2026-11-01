/** 容量值只由认证后的后端配置接口提供。 */
export interface UploadLimits {
  maxFileMb: number
  maxBatchFiles: number
  maxBatchMb: number
}

export function parseUploadLimits(payload: unknown): UploadLimits {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new Error('上传限制响应无效')
  }
  const data = payload as Record<string, unknown>
  const values = [data.max_file_mb, data.max_batch_files, data.max_batch_mb]
  if (values.some((value) => typeof value !== 'number' || !Number.isSafeInteger(value) || value <= 0)) {
    throw new Error('上传限制响应无效')
  }
  const [maxFileMb, maxBatchFiles, maxBatchMb] = values as number[]
  if (!Number.isSafeInteger(maxFileMb! * 1024 * 1024) || !Number.isSafeInteger(maxBatchMb! * 1024 * 1024)) {
    throw new Error('上传限制响应无效')
  }
  return { maxFileMb: maxFileMb!, maxBatchFiles: maxBatchFiles!, maxBatchMb: maxBatchMb! }
}
