import { expect, test } from '@playwright/test'

import { auditProgressDisplay } from '../src/utils/audit-progress'


test('single audit never invents a percentage while backend request is running', () => {
  expect(auditProgressDisplay('running')).toEqual({
    label: '正在执行合同审查…',
    percentage: null,
    indeterminate: true,
  })
})

test('single audit only reports completion after the request finishes', () => {
  expect(auditProgressDisplay('done')).toEqual({
    label: '审查完成',
    percentage: 100,
    indeterminate: false,
  })
})
