import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export type NotifyType = 'alert' | 'rectify' | 'info'

export interface NotifyItem {
  id: string
  type: NotifyType
  title: string
  text: string
  time: string
  read: boolean
}

let seq = 0
function nextId() {
  seq += 1
  return `N${Date.now()}${seq}`
}

export const useNotifyStore = defineStore('notify', () => {
  // 预置几条，体现通知系统存在
  const items = ref<NotifyItem[]>([
    {
      id: nextId(),
      type: 'info',
      title: '系统就绪',
      text: 'OpenClaw 一体机已连接，审查服务正常。',
      time: '刚刚',
      read: false,
    },
  ])

  const unreadCount = computed(() => items.value.filter((n) => !n.read).length)
  const hasUnread = computed(() => unreadCount.value > 0)

  function push(type: NotifyType, title: string, text: string) {
    items.value.unshift({ id: nextId(), type, title, text, time: '刚刚', read: false })
  }

  function markAllRead() {
    items.value.forEach((n) => (n.read = true))
  }

  return { items, unreadCount, hasUnread, push, markAllRead }
})
