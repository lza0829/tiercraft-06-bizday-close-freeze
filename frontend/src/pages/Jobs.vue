<script setup>
import { onMounted, ref } from 'vue'
import { getJson, postJson } from '../api'

const domains = ref([])
const domainId = ref(1)
const bizDay = ref('')
const jobs = ref([])
const err = ref('')
const busy = ref(false)

async function refresh() {
  jobs.value = await getJson(`/api/jobs?domain_id=${domainId.value}`)
}

onMounted(async () => {
  try {
    domains.value = await getJson('/api/domains')
    if (domains.value.length) domainId.value = domains.value[0].id
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
})

async function run(step) {
  busy.value = true
  err.value = ''
  try {
    const url = step === '明细'
      ? '/api/jobs/paste-to-detail'
      : '/api/jobs/detail-to-summary'
    await postJson(url, {
      domain_id: domainId.value,
      biz_day: bizDay.value || null,
    })
    await refresh()
  } catch (e) {
    // 关闭日拒绝同样已落任务结果，刷新让「拒绝」记录出现在列表
    err.value = String(e.message || e)
    await refresh()
  } finally {
    busy.value = false
  }
}
</script>
<template>
  <div>
    <h2>分层任务</h2>
    <p class="lead">
      按主题域推进：先贴源到明细，再明细到汇总。指定业务日即为定点重算；
      已关闭业务日会被拒绝并写入任务结果，全量重跑自动跳过已关闭日。
    </p>
    <div class="toolbar">
      <label>
        主题域
        <select v-model.number="domainId" @change="refresh">
          <option v-for="d in domains" :key="d.id" :value="d.id">{{ d.name }}</option>
        </select>
      </label>
      <label>业务日（留空为全量重跑）<input v-model="bizDay" type="date" /></label>
      <button :disabled="busy" @click="run('明细')">跑贴源到明细</button>
      <button class="secondary" :disabled="busy" @click="run('汇总')">跑明细到汇总</button>
    </div>
    <p v-if="err" class="err">{{ err }}</p>
    <div class="panel">
      <table>
        <thead>
          <tr><th>编号</th><th>步骤</th><th>状态</th><th>业务日</th><th>说明</th><th>输入</th><th>写入</th><th>剔除</th><th>拒绝</th><th>时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="j in jobs" :key="j.id">
            <td>{{ j.id }}</td>
            <td>{{ j.step_label || j.step }}</td>
            <td :class="j.status === '拒绝' ? 'warn' : (j.reject_count ? 'warn' : 'ok')">{{ j.status }}</td>
            <td>{{ j.biz_day || '全量' }}</td>
            <td>{{ j.message }}</td>
            <td>{{ j.in_count }}</td>
            <td>{{ j.out_count }}</td>
            <td>{{ j.drop_count }}</td>
            <td>{{ j.reject_count }}</td>
            <td>{{ j.created_at }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!jobs.length" class="muted">还没有任务记录。</p>
    </div>
  </div>
</template>
