<script setup lang="ts">
// 顶栏通知铃铛：未读红点 + 下拉列表。点 rectify 类跳整改跟踪。
import { useRouter } from 'vue-router'
import { useNotifyStore, type NotifyType } from '@/stores/notify'

const router = useRouter()
const notify = useNotifyStore()

const dotColor: Record<NotifyType, string> = {
  alert: 'var(--seal)',
  rectify: 'var(--brass)',
  info: 'var(--ivory-dim)',
}

function onItem(type: NotifyType) {
  if (type === 'rectify') router.push('/rectify')
}
</script>

<template>
  <el-popover placement="bottom-end" :width="320" trigger="click" popper-class="notify-popover">
    <template #reference>
      <button class="bell" type="button" aria-label="通知与预警">
        <el-icon :size="18"><Bell /></el-icon>
        <i v-if="notify.hasUnread" class="dot" />
      </button>
    </template>
    <div class="notify-head">
      <b>通知与预警</b>
      <el-button link type="primary" size="small" @click="notify.markAllRead()">全部已读</el-button>
    </div>
    <div class="notify-list">
      <el-empty v-if="!notify.items.length" description="暂无通知" :image-size="60" />
      <div
        v-for="n in notify.items"
        :key="n.id"
        class="notify-item"
        :class="{ unread: !n.read }"
        @click="onItem(n.type)"
      >
        <span class="n-dot" :style="{ background: dotColor[n.type] }" />
        <div class="n-body">
          <div class="n-title">{{ n.title }}<span class="n-time">{{ n.time }}</span></div>
          <p class="n-text">{{ n.text }}</p>
        </div>
      </div>
    </div>
  </el-popover>
</template>

<style scoped>
.bell {
  position: relative;
  width: 38px;
  height: 38px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--ink-2);
  color: var(--ivory-dim);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s var(--ease);
}
.bell:hover {
  border-color: var(--brass);
  color: var(--brass);
}
.dot {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--seal);
  border: 1.5px solid var(--ink-2);
}
.notify-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--line);
  margin-bottom: 6px;
}
.notify-head b {
  font-family: var(--serif);
  color: var(--ivory);
}
.notify-list {
  max-height: 340px;
  overflow-y: auto;
}
.notify-item {
  display: flex;
  gap: 10px;
  padding: 10px 6px;
  border-radius: var(--r-sm);
  cursor: pointer;
}
.notify-item:hover {
  background: var(--brass-soft);
}
.notify-item.unread {
  background: var(--ink-3);
}
.n-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-top: 6px;
  flex: none;
}
.n-body {
  flex: 1;
  min-width: 0;
}
.n-title {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 600;
  color: var(--ivory);
}
.n-time {
  font-size: 11px;
  color: var(--muted);
  font-weight: 400;
  font-family: var(--mono);
}
.n-text {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--ivory-dim);
  line-height: 1.5;
}
</style>
