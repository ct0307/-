import { expect, test } from '@playwright/test'

import { extractHttpErrorDetail } from '../src/api/client'

test('reads stable code and message from structured backend errors', () => {
  expect(extractHttpErrorDetail({ code: 'IMPORT_ITEM_NOT_READY', message: '合同尚未就绪' })).toEqual({
    code: 'IMPORT_ITEM_NOT_READY',
    message: '合同尚未就绪',
  })
  expect(extractHttpErrorDetail({ code: 'LEGACY_ERROR', detail: '旧接口错误' })).toEqual({
    code: 'LEGACY_ERROR',
    message: '旧接口错误',
  })
})
