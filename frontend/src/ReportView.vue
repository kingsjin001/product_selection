<script setup>
// 页面、追问与导出都绑定不可变报告，成本修订通过独立任务交付。
import { ref, computed, watch } from 'vue'
import { api, jsonPost } from './api'
const props = defineProps({ runId: String })
const emit = defineEmits(['revised'])
const source = ref(null)
const report = computed(() => source.value?.report)
const error = ref('')
const busy = ref(false)
const scenario = ref('base')
const selected = computed(() => report.value?.economics.scenarios.find(row => row.name === scenario.value))
const openEvidence = ref([])
const cited = computed(() => new Set(report.value?.research.claims.flatMap(row => row.evidence_ids) || []))
const evidence = computed(() => report.value?.evidence.filter(row => cited.value.has(row.id)) || [])
const question = ref('基准情景的利润是多少？')
const questionMode = ref('extractive')
const answer = ref(null)
const history = ref([])
const costDraft = ref({})
const costsEnabled = ref(false)
const costFields = { sale_price:'售价', procurement:'采购成本', shipping:'运输成本', packaging:'包材',
  platform_rate:'平台费率（0～1）', commission_rate:'佣金率（0～1）', advertising:'广告分摊',
  return_loss:'退货损失分摊', other:'其他成本含税费' }
const defaults = { currency:'USD', source:'手工成本假设', observed_on:new Date().toISOString().slice(0,10),
  assumed:true, sale_price:'25', procurement:'6', shipping:'4', packaging:'.5', platform_rate:'.06',
  commission_rate:'.1', advertising:'2', return_loss:'.75', other:'.5' }
async function load() {
  error.value = ''
  try {
    source.value = await api(`/api/reports/${props.runId}`)
    costDraft.value = {...defaults, ...(report.value.economics.input || {})}
    history.value = await api(`/api/reports/${props.runId}/questions`)
  } catch (err) { error.value = err.message }
}
watch(() => props.runId, () => { source.value = null; answer.value = null; openEvidence.value = []; load() }, { immediate: true })
async function download(format) {
  busy.value = true; error.value = ''
  try {
    const exported = await api(`/api/reports/${props.runId}/exports`, jsonPost({format}))
    const link = document.createElement('a'); link.href = exported.download_url; link.click()
  } catch (err) { error.value = err.message }
  finally { busy.value = false }
}
async function ask() {
  busy.value = true; error.value = ''
  try {
    answer.value = await api(`/api/reports/${props.runId}/questions`, jsonPost({question:question.value, mode:questionMode.value}))
    history.value = await api(`/api/reports/${props.runId}/questions`)
  } catch (err) { error.value = err.message }
  finally { busy.value = false }
}
async function revise() {
  busy.value = true; error.value = ''
  try {
    const next = await api(`/api/reports/${props.runId}/revisions`, jsonPost(costDraft.value, crypto.randomUUID()))
    emit('revised', next)
  } catch (err) { error.value = err.message }
  finally { busy.value = false }
}
function showEvidence(ids) { openEvidence.value = [...new Set([...openEvidence.value, ...ids])] }
function safeSource(url) { return /^https?:\/\//i.test(url || '') ? url : null }
</script>
<template>
  <section v-if="report" class="card report">
    <div class="row"><div><p class="eyebrow">冻结报告</p><h2>{{ report.product.name }}</h2></div><span class="badge">{{ report.mode }}</span></div>
    <p class="summary">{{ report.research.summary }}</p>
    <p class="hint">样例数据为合成资料；引用可定位并不代表结论已经过人工核验。</p>
    <div class="actions"><button :disabled="busy" @click="download('docx')">下载 Word</button><button class="secondary" :disabled="busy" @click="download('md')">下载 Markdown</button><button class="secondary" :disabled="busy" @click="download('json')">下载 JSON</button></div>
    <h3>有据可查的声明</h3>
    <article v-for="(claim,index) in report.research.claims" :key="index" class="claim">
      <span class="badge">{{ claim.kind === 'inference' ? '推断' : '观察' }}</span>
      <p>{{ claim.statement }}</p><p v-for="limit in claim.limitations" :key="limit" class="hint">{{ limit }}</p>
      <button class="link-button" @click="showEvidence(claim.evidence_ids)">展开引用 {{ claim.evidence_ids.join(' / ') }}</button>
    </article>
    <h3>贡献利润情景</h3>
    <template v-if="report.economics.status === 'ok'">
      <label>选择情景<select v-model="scenario"><option value="conservative">保守（售价 × 0.9）</option><option value="base">基准（售价 × 1）</option><option value="optimistic">乐观（售价 × 1.1）</option></select></label>
      <div v-if="selected" class="metrics"><div><small>收入</small><strong>{{ selected.revenue }}</strong></div><div><small>成本</small><strong>{{ selected.cost }}</strong></div><div><small>贡献利润 · {{ report.economics.currency }}</small><strong>{{ selected.contribution }}</strong></div></div>
      <p v-for="note in report.economics.notes" :key="note" class="hint">{{ note }}</p>
    </template>
    <p v-else>成本不完整，未计算利润。缺失：{{ report.economics.missing.join('、') }}</p>
    <h3>缺失与下一步</h3>
    <ul><li v-for="item in [...report.research.missing_data,...report.research.next_steps]" :key="item">{{ item }}</li></ul>
    <h3>引用证据</h3>
    <details v-for="item in evidence" :key="item.id" :open="openEvidence.includes(item.id)">
      <summary>{{ item.id }} · {{ item.version }}</summary><p>{{ item.text }}</p>
      <p class="hint">{{ item.payload.data_kind }} · {{ item.observed_at }}</p>
      <a v-if="safeSource(item.source_url)" :href="item.source_url" target="_blank" rel="noopener noreferrer">查看原始来源</a>
      <p class="hint">此处展示报告生成时冻结的版本。</p>
    </details>
    <h3>追问这份报告</h3>
    <form @submit.prevent="ask"><label>问题<textarea v-model="question" rows="2" required /></label>
      <label>回答方式<select v-model="questionMode"><option value="extractive">在报告中定位（无需模型）</option><option value="model">真实模型解读（单次请求）</option></select></label>
      <button :disabled="busy">提交追问</button></form>
    <article v-if="answer" class="claim"><p class="summary">{{ answer.answer }}</p><p class="hint">引用：{{ answer.evidence_ids.join('、') || '成本计算或缺失说明' }}</p><p v-for="limit in answer.limitations" :key="limit" class="hint">{{ limit }}</p></article>
    <details v-if="history.length"><summary>追问记录 {{ history.length }} 条</summary><div v-for="row in history" :key="row.id"><b>{{ row.request.question }}</b><p>{{ row.response?.answer || row.status }}</p></div></details>
    <h3>调整成本生成新版本</h3>
    <p class="hint">沿用这份报告的证据快照，生成新的任务和报告，原报告保持不变。默认数字仅为可编辑演示假设。</p>
    <button class="secondary" @click="costsEnabled = !costsEnabled">{{ costsEnabled ? '收起成本编辑' : '编辑成本假设' }}</button>
    <form v-if="costsEnabled" @submit.prevent="revise" class="cost-editor">
      <div class="fields"><label v-for="(label,key) in costFields" :key="key">{{ label }}<input v-model="costDraft[key]" type="number" step="any" min="0" required></label><label>币种<input v-model="costDraft.currency" required maxlength="3"></label><label>来源<input v-model="costDraft.source" required></label><label>日期<input type="date" v-model="costDraft.observed_on" required></label></div>
      <label class="checkbox"><input type="checkbox" v-model="costDraft.assumed">这些参数包含假设</label><button :disabled="busy">创建成本修订任务</button>
    </form>
    <details><summary>版本与完整性</summary><p class="mono">报告 {{ source.report_hash }}</p><p class="mono">快照 {{ report.snapshot_hash }}</p><p>模型 {{ report.versions.model }} · 提示词 {{ report.versions.prompt }}</p><p v-if="report.versions.parent_run_id">来源报告 {{ report.versions.parent_run_id }}</p></details>
  </section>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
</template>
