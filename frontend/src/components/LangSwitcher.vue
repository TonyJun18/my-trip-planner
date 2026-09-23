<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { SUPPORT_LOCALES, setLocale } from '@/i18n'

const { locale } = useI18n()

const current = computed(() => SUPPORT_LOCALES.find((l) => l.code === locale.value) || SUPPORT_LOCALES[0])

function onCommand(cmd) {
  if (cmd) setLocale(cmd)
}
</script>

<template>
  <el-dropdown trigger="click" @command="onCommand">
    <span class="lang-switch" tabindex="0">
      <el-icon style="margin-right: 4px"><Switch /></el-icon>
      <span class="lang-label">{{ current.label }}</span>
      <el-icon class="chevron"><ArrowDown /></el-icon>
    </span>
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item
          v-for="l in SUPPORT_LOCALES"
          :key="l.code"
          :command="l.code"
          :disabled="l.code === locale"
        >
          {{ l.label }}
        </el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<style scoped>
.lang-switch {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  cursor: pointer;
  padding: 6px 10px;
  border-radius: var(--radius-full);
  border: 1px solid var(--line);
  background: #fff;
  color: var(--ink-2);
  font-size: 13px;
  transition: box-shadow 0.2s, border-color 0.2s;
}
.lang-switch:hover {
  box-shadow: var(--shadow-card);
  border-color: var(--brand);
  color: var(--brand);
}
.lang-label { min-width: 28px; text-align: center; }
.chevron { font-size: 12px; color: var(--faint); }
</style>