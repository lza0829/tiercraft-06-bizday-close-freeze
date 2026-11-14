<script setup>
import { onMounted, ref } from 'vue'
import { getJson, postJson } from '../api'

const domains = ref([])
const domainId = ref(1)
const rows = ref([])
const err = ref('')
const busy = ref(false)
const newDay = ref('')
const reason = ref('')

async function refresh() {
  rows.value = await getJson(`/api/biz-days/overview?domain_id=${domainId.value}`)
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

async function closeDay() {
  err.value = ''
  if (!newDay.value) {
    err.value = '请填写要关闭的业务日'
    return
  }
  busy.value = true
  try {
    await postJson('/api/closed-days/close', {
      domain_id: domainId.value,
      biz_day: newDay.value,
      reason: reason.value,
    })
    newDay.value = ''
    reason.value = ''
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

async function reopen(day) {
  err.value = ''
  busy.value = true
  try {
    await postJson('/api/closed-days/reopen', {
      domain_id: domainId.value,
      biz_day: day,
    })
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}
</script>
<template>
  <div>
    <h2>业务日关闭</h2>
    <p class="lead">
      维护主题域的业务日关闭名单。已关闭日禁止贴源装载，并禁止针对该日的贴源到明细、明细到汇总（含定点重算）；
      拒绝原因写入装载或任务结果，刷新后仍在。
    </p>
    <div class="toolbar">
      <label>
        主题域
        <select v-model.number="domainId" @change="refresh">
          <option v-for="d in domains" :key="d.id" :value="d.id">{{ d.name }}</option>
        </select>
      </label>
    </div>
    <div class="panel">
      <h3>关闭业务日</h3>
      <div class="toolbar">
        <label>业务日 <input v-model="newDay" type="date" /></label>
        <label>关闭原因 <input v-model="reason" type="text" placeholder="如：月末结账完成" /></label>
        <button :disabled="busy" @click="closeDay">关闭该业务日</button>
      </div>
    </div>
    <p v-if="err" class="err">{{ err }}</p>
    <div class="panel">
      <h3>业务日名单（与贴源按日计数同源）</h3>
      <table>
        <thead>
          <tr><th>业务日</th><th>状态</th><th>贴源行数</th><th>关闭原因</th><th>关闭时间</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.biz_day">
            <td>{{ r.biz_day }}</td>
            <td>
              <span v-if="r.closed" class="badge badge-closed">已关闭</span>
              <span v-else class="badge badge-open">未关闭</span>
            </td>
            <td>{{ r.paste_count }}</td>
            <td>{{ r.reason || '—' }}</td>
            <td>{{ r.closed_at || '—' }}</td>
            <td>
              <button
                v-if="r.closed"
                class="secondary"
                :disabled="busy"
                @click="reopen(r.biz_day)"
              >重新打开</button>
              <span v-else class="muted">—</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="!rows.length" class="muted">该主题域暂无业务日记录。</p>
    </div>
  </div>
</template>
