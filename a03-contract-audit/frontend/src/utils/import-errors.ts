import type { ImportItem } from '@/api/imports'

export interface ImportErrorMeta {
  message: string
  action: string
  retryable: boolean
}

const IMPORT_ERRORS: Record<string, ImportErrorMeta> = {
  PDF_CORRUPT: {
    message: 'PDF 文件已损坏',
    action: '重新获取原文件后上传',
    retryable: false,
  },
  DOCX_CORRUPT: {
    message: 'Word 文件已损坏',
    action: '重新获取原文件后上传',
    retryable: false,
  },
  UNSUPPORTED_FILE_TYPE: {
    message: '不支持的文件类型',
    action: '请上传 PDF、Word 或 TXT 文件',
    retryable: false,
  },
  EMPTY_FILE: {
    message: '文件内容为空',
    action: '请选择包含合同内容的文件',
    retryable: false,
  },
  FILE_TOO_LARGE: {
    message: '文件超过大小限制',
    action: '压缩或拆分文件后重新上传',
    retryable: false,
  },
  BATCH_TOO_LARGE: {
    message: '本批次文件总量超过限制',
    action: '减少本批次文件数量后重新上传',
    retryable: false,
  },
  DUPLICATE_FILENAME: {
    message: '本批次存在同名文件',
    action: '移除重复文件或修改文件名后上传',
    retryable: false,
  },
  PDF_TEXT_EMPTY: {
    message: '未能从文件中提取有效文本',
    action: '重新导出 PDF 后上传',
    retryable: false,
  },
  PDF_TEXT_ENCODING_ERROR: {
    message: 'PDF 文本编码异常',
    action: '重新导出 PDF 后上传',
    retryable: false,
  },
  OCR_UNAVAILABLE: {
    message: '扫描件识别服务未就绪',
    action: '联系管理员修复服务后重新解析',
    retryable: true,
  },
  OCR_TIMEOUT: {
    message: '扫描件识别超时',
    action: '稍后重试，持续超时请拆分文件',
    retryable: true,
  },
  OCR_LIMIT_EXCEEDED: {
    message: '文件超出扫描件识别限制',
    action: '拆分或压缩文件后重新上传',
    retryable: false,
  },
  OCR_PROTOCOL_ERROR: {
    message: '扫描件识别服务响应异常',
    action: '稍后重新解析',
    retryable: true,
  },
  PARSE_INTERNAL_ERROR: {
    message: '合同解析失败',
    action: '稍后重新解析',
    retryable: true,
  },
}

export function importErrorMeta(item: ImportItem): ImportErrorMeta {
  const fallback = IMPORT_ERRORS[item.error_code ?? '']
  return {
    message: item.error_message?.trim() || fallback?.message || '文件处理失败',
    action: item.error_action?.trim() || fallback?.action || '请检查文件后重新上传',
    retryable: item.retryable ?? fallback?.retryable ?? false,
  }
}
