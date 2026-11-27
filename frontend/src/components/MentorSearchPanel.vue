<template>
  <div class="modal-backdrop" data-testid="mentor-panel">
    <section class="modal mentor-panel">
      <header class="mentor-head">
        <div>
          <h3>按学期检索导师</h3>
          <p class="mentor-goal">
            目标 <strong>{{ goal.目标编号 || `#${goal.id}` }}</strong>
            · 责任教师 {{ goal.责任教师 }}
            · 学期 <strong>{{ goal.起始学期 }}</strong>
          </p>
        </div>
        <button class="btn ghost" type="button" data-testid="mentor-close" @click="$emit('close')">关闭</button>
      </header>

      <p class="mentor-hint">
        只展示 {{ goal.起始学期 }} 有剩余指导名额的导师；其他学期的名额不能替代本目标的学期。
      </p>

      <form class="analysis-form" @submit.prevent="search">
        <label>
          <span>指导方向</span>
          <input
            v-model="direction"
            data-testid="mentor-direction"
            placeholder="如：课堂教学"
            list="mentor-directions"
          />
          <datalist id="mentor-directions">
            <option v-for="item in directions" :key="item" :value="item" />
          </datalist>
        </label>
        <button class="btn primary" data-testid="mentor-search" type="submit" :disabled="loading">
          {{ loading ? '检索中…' : '按方向检索' }}
        </button>
        <button class="btn ghost" type="button" data-testid="mentor-search-all" @click="searchAll">
          查看全部方向
        </button>
      </form>

      <p v-if="errorMessage" class="error-text" data-testid="mentor-error">{{ errorMessage }}</p>

      <table class="data-table mentor-table">
        <thead>
          <tr>
            <th>导师</th><th>指导方向</th><th>学期</th><th>职称</th><th>剩余名额</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="mentor in mentors" :key="mentor.id" :data-testid="`mentor-${mentor.id}`">
            <td>{{ mentor.导师姓名 }}</td>
            <td>{{ mentor.指导方向 }}</td>
            <td>{{ mentor.学期 }}</td>
            <td>{{ mentor.职称 }}</td>
            <td>{{ mentor.剩余名额 }}</td>
            <td>
              <button
                class="link"
                type="button"
                :data-testid="`mentor-pick-${mentor.id}`"
                :disabled="busy"
                @click="pick(mentor)"
              >
                发起结对
              </button>
            </td>
          </tr>
          <tr v-if="!mentors.length">
            <td colspan="6" class="empty-state">
              {{ searched ? '该学期没有符合条件的可指导导师，请调整指导方向' : '选择指导方向后检索' }}
            </td>
          </tr>
        </tbody>
      </table>

      <div v-if="status" class="pairing-status" data-testid="pairing-status">
        <div class="pairing-line">
          <span class="stat-label">候选资格</span>
          <strong :class="status.已具备确认资格 ? 'qualification-ok' : 'qualification-bad'">
            {{ status.候选资格 || '无' }}
          </strong>
          <span class="pairing-state">{{ status.结对状态 }}</span>
        </div>
        <p class="pairing-message">{{ status.说明 }}</p>
        <p v-if="status.待办事项" class="pairing-todo" data-testid="pairing-todo">
          待办：{{ status.待办事项 }}
        </p>
        <p v-if="status.需更换导师" class="error-text" data-testid="pairing-change">
          请更换导师后重新检索发起结对
        </p>
        <div class="page-actions">
          <button
            v-if="status.结对记录编号 && status.结对状态 !== '已结对'"
            class="btn primary"
            type="button"
            data-testid="pairing-accept"
            :disabled="busy"
            @click="accept"
          >
            模拟导师受理
          </button>
          <button class="btn" type="button" data-testid="pairing-refresh" :disabled="busy" @click="refreshStatus">
            回看候选资格
          </button>
        </div>
      </div>

      <p v-if="successMessage" class="success-text" data-testid="pairing-success">{{ successMessage }}</p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { acceptPairing, initiatePairing, loadPairingStatus, searchMentors } from '@/api/backend-service'
import type { EntryRow, MentorRow, PairingStatus } from '@/data/types'

const props = defineProps<{ goal: EntryRow }>()
const emit = defineEmits<{ close: []; updated: [] }>()

const direction = ref('')
const mentors = ref<MentorRow[]>([])
const status = ref<PairingStatus | null>(null)
const searched = ref(false)
const loading = ref(false)
const busy = ref(false)
const errorMessage = ref('')
const successMessage = ref('')

const goalId = computed(() => Number(props.goal.id))
const directions = computed(() => [...new Set(mentors.value.map((item) => item.指导方向))])

function describe(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback
}

async function search() {
  loading.value = true
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const payload = await searchMentors(goalId.value, direction.value.trim())
    mentors.value = payload.items
    searched.value = true
  } catch (error) {
    errorMessage.value = describe(error, '导师检索失败')
  } finally {
    loading.value = false
  }
}

function searchAll() {
  direction.value = ''
  void search()
}

async function refreshStatus() {
  try {
    status.value = await loadPairingStatus(goalId.value)
  } catch (error) {
    errorMessage.value = describe(error, '候选资格读取失败')
  }
}

async function pick(mentor: MentorRow) {
  busy.value = true
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const result = await initiatePairing(goalId.value, {
      rosterId: mentor.id,
      direction: direction.value.trim() || undefined,
    })
    successMessage.value = result.message
    await refreshStatus()
    await search()
    emit('updated')
  } catch (error) {
    errorMessage.value = describe(error, '发起结对失败')
    // 检索结果和候选资格都可能已经变化，重新拉一遍再让用户判断。
    await Promise.all([refreshStatus(), search()])
    emit('updated')
  } finally {
    busy.value = false
  }
}

async function accept() {
  const pairId = status.value?.结对记录编号
  if (!pairId) return
  busy.value = true
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const result = await acceptPairing(pairId)
    successMessage.value = result.message
    await refreshStatus()
    await search()
    emit('updated')
  } catch (error) {
    errorMessage.value = describe(error, '受理结对失败')
    await refreshStatus()
    emit('updated')
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  await Promise.all([search(), refreshStatus()])
})
</script>
