<script setup>
// 后台任务页面：刷新恢复状态，事件按持久序号去重。
import { ref, onMounted, onUnmounted } from 'vue'
import ImportPanel from './ImportPanel.vue'
import ReportView from './ReportView.vue'
import ReviewPanel from './ReviewPanel.vue'
import MemoryPanel from './MemoryPanel.vue'

const product = ref('prod-cn-001')
const mode = ref('workflow')
const reviewPolicy = ref('auto')
const question = ref('请根据评论与规则给出选品条件，并明确缺失数据。')
const task = ref(null)
const events = ref([])
const error = ref('')
const submitting = ref(false)
const page = ref('research')
const products = ref([])
const reports = ref([])
const reportId = ref('')
const restoreId = ref('')
let stream = null
let key = null
let fingerprint = ''
const labels = { waiting_for_review: '等待人工复核', queued: '等待执行', running: '研究中', cancelling: '正在取消', cancelled: '已取消', completed: '报告已完成', failed: '执行失败' }

async function api(path, options = {}) {
  const response = await fetch(path, options)
  const body = await response.json()
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail))
  return body
}

async function refresh() {
  if (task.value) task.value = await api(`/api/tasks/${task.value.id}`)
}

async function refreshLists() {
  try { [products.value, reports.value] = await Promise.all([api('/api/products'), api('/api/reports')]) }
  catch (err) { error.value = err.message }
}

function acceptRevision(next) {
  task.value = next; events.value = []; page.value = 'research'
  localStorage.setItem('selection-task', next.id); subscribe(next.id)
}

async function restoreTask() {
  // 人工等待可能跨多天，通过已知编号找回任务和草稿。
  try { acceptRevision(await api(`/api/tasks/${restoreId.value.trim()}`)) }
  catch (err) { error.value = err.message }
}

function viewReport(id) {
  reportId.value = id; page.value = 'reports'; refreshLists()
}

function subscribe(id) {
  stream?.close()
  // 刷新时从 0 回放以恢复完整事件列表；同一连接自动携带 Last-Event-ID。
  stream = new EventSource(`/api/tasks/${id}/events`)
  stream.onmessage = async (message) => {
    const event = JSON.parse(message.data)
    if (!events.value.some(row => row.event_seq === event.event_seq)) events.value.push(event)
    await refresh().catch(err => { error.value = err.message })
    if (['completed', 'failed', 'cancelled'].includes(task.value?.status) &&
        event.event_seq >= task.value.event_seq) stream.close()
  }
  stream.onerror = () => { /* EventSource 自动重连，断线不取消研究。 */ }
}

async function submit() {
  submitting.value = true
  error.value = ''
  const body = JSON.stringify({ product_id: product.value, mode: mode.value, question: question.value, review_policy: reviewPolicy.value })
  // 网络失败后保留相同请求的键；明确提交成功后下一次点击才生成新键。
  if (!key || fingerprint !== body) { key = crypto.randomUUID(); fingerprint = body }
  try {
    task.value = await api('/api/tasks', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body })
    localStorage.setItem('selection-task', task.value.id)
    events.value = []
    subscribe(task.value.id)
    key = null
  } catch (err) { error.value = err.message }
  finally { submitting.value = false }
}

async function action(name) {
  try { task.value = await api(`/api/tasks/${task.value.id}/${name}`, { method: 'POST' }); subscribe(task.value.id) }
  catch (err) { error.value = err.message }
}

onMounted(async () => {
  refreshLists()
  const id = localStorage.getItem('selection-task')
  if (id) {
    try { task.value = await api(`/api/tasks/${id}`); subscribe(id) }
    catch (err) { error.value = err.message }
  }
})
onUnmounted(() => stream?.close())
</script>

<template>
  <main>
    <header><p class="eyebrow">个人研究 · 证据优先</p><h1>选品研究工作台</h1><p>从商品证据出发，记录研究过程、条件与缺失项。</p></header>
    <nav class="actions"><button :class="{secondary: page !== 'research'}" @click="page='research'">研究任务</button><button :class="{secondary: page !== 'imports'}" @click="page='imports'">导入资料</button><button :class="{secondary: page !== 'reports'}" @click="page='reports'; refreshLists()">报告库</button><button class="secondary" @click="page='memory'">偏好与记忆</button></nav>
    <MemoryPanel v-if="page === 'memory'" />
    <ImportPanel v-if="page === 'imports'" @imported="refreshLists" />
    <section v-if="page === 'reports'" class="card">
      <h2>选择已完成报告</h2>
      <label>报告<select v-model="reportId"><option value="">请选择</option><option v-for="row in reports" :value="row.id" :key="row.id">{{ row.name }} · {{ row.mode }} · {{ row.created_at }} · {{ row.id.slice(0,8) }}</option></select></label>
      <label>或输入运行编号<input v-model="reportId" placeholder="报告 run_id"></label>
    </section>
    <ReportView v-if="page === 'reports' && reportId" :run-id="reportId" @revised="acceptRevision" />
    <section v-if="page === 'research'" class="card">
      <h2>开始一次研究</h2>
      <details><summary>恢复已有任务</summary><form @submit.prevent="restoreTask"><label>任务编号<input v-model="restoreId" required></label><button class="secondary">打开已有任务</button></form></details>
      <form @submit.prevent="submit">
        <div class="fields">
          <label>商品编号<input v-model="product" list="products" required><datalist id="products"><option v-for="row in products" :key="row.id" :value="row.id">{{ row.name }} · {{ row.market }}</option></datalist></label>
          <label>研究方式<select v-model="mode"><option value="fixed">原文整理（无需聊天模型）</option><option value="prompt">单次模型分析</option><option value="workflow">固定检索后分析</option><option value="agent">单 Agent 研究</option><option value="multi">多 Agent 专项研究</option></select></label>
        </div>
        <label>发布前复核<select v-model="reviewPolicy"><option value="auto">缺失或冲突时复核</option><option value="always">始终复核</option><option value="off">直接生成报告</option></select></label>
        <label>研究问题<textarea v-model="question" rows="3" required /></label>
        <button :disabled="submitting">{{ submitting ? '正在提交…' : '创建研究任务' }}</button>
      </form>
      <p class="hint">内置数据为中文合成样例。未提供完整成本时，报告会明确显示无法计算贡献利润。</p>
    </section>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <section v-if="task && page === 'research'" class="card">
      <div class="row"><h2>{{ labels[task.status] || task.status }}</h2><span class="badge">{{ task.stage }}</span></div>
      <p class="mono">{{ task.id }}</p>
      <p>执行次数：{{ task.attempts }} · 刷新页面不影响后台执行</p>
      <button v-if="['queued','running','waiting_for_review'].includes(task.status)" class="secondary" @click="action('cancel')">取消研究</button>
      <button v-if="task.status === 'failed'" @click="action('resume')">从检查点恢复</button>
      <p v-if="task.error" class="error">停止原因：{{ task.error }}</p>
      <ol class="timeline"><li v-for="event in events" :key="event.event_seq"><small>#{{ event.event_seq }} · {{ event.timestamp }}</small><p>{{ event.message }}</p></li></ol>
      <button v-if="task.status === 'completed'" @click="viewReport(task.id)">查看完整报告</button>
    </section>
    <ReviewPanel v-if="page === 'research' && task?.status === 'waiting_for_review'" :run-id="task.id" @decided="refresh" @revised="acceptRevision" />
  </main>
</template>
