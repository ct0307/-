<script setup lang="ts">
// 演示数据标识：挂在使用 mock 数据的页面，明确"待后端接入"。
</script>

<template>
  <span class="demo-badge">
    <el-icon :size="13"><InfoFilled /></el-icon>
    演示数据 · 待后端接入
  </span>
</template>

<style scoped>
.demo-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 20px;
  font-size: 12px;
  color: var(--amber);
  background: var(--amber-soft);
  font-family: var(--mono);
}
</style>
