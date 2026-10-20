<script setup>
// 人工复核绑定完整草稿和摘要，避免过期页面误批。
import { ref, watch } from 'vue'
import { api, jsonPost } from './api'
const props = defineProps({ runId: String })
const emit = defineEmits(['decided', 'revised'])
const review = ref(null), feedback = ref(''), error = ref(''), busy = ref(false)
watch(() => props.runId, async () => {
  try { review.value = await api(`/api/tasks/${props.runId}/review`) }
  catch (err) { error.value = err.message }
}, { immediate: true })
async function decide(action) {
  busy.value = true; error.value = ''
  try {
    const result = await api(`/api/tasks/${props.runId}/review`, jsonPost({draft_hash: review.value.draft_hash, action, feedback: feedback.value}))
    if (result.revision_task_id) emit('revised', await api(`/api/tasks/${result.revision_task_id}`))
    else emit('decided')
  } catch (err) { error.value = err.message }
  finally { busy.value = false }
}
</script>
<template>
  <section v-if="review" class="card">
    <h2>发布前复核</h2><p>草稿尚未发布。等待期间不占用 Worker；批准后再次校验证据版本。</p>
    <ul><li v-for="reason in review.reasons" :key="reason">{{ reason }}</li></ul>
    <h3>{{ review.draft.product.name }}</h3><p>{{ review.draft.research.summary }}</p>
    <article v-for="(claim,index) in review.draft.research.claims" :key="index" class="claim">
      <p>{{ claim.statement }}</p><small>{{ claim.evidence_ids.join('、') }}</small>
      <p v-for="limit in claim.limitations" :key="limit" class="hint">{{ limit }}</p>
    </article>
    <h3>成本与缺失</h3>
    <p v-if="review.draft.economics.status !== 'ok'">未计算利润：{{ review.draft.economics.missing.join('、') }}</p>
    <p v-for="scenario in review.draft.economics.scenarios" :key="scenario.name">{{ scenario.name }}：贡献利润 {{ scenario.contribution }} {{ review.draft.economics.currency }}</p>
    <ul><li v-for="item in review.draft.research.missing_data" :key="item">{{ item }}</li></ul>
    <details><summary>核对原始证据与来源</summary><article v-for="item in review.draft.evidence" :key="item.id">
      <b>{{ item.id }} · {{ item.version }}</b><p>{{ item.text }}</p><p>{{ item.source_url }}</p>
    </article></details>
    <details><summary>完整草稿 JSON</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">{{ JSON.stringify(review.draft,null,2) }}</pre></details>
    <label>复核意见（要求修改时必填）<textarea v-model="feedback" maxlength="500" rows="3" /></label>
    <div class="actions"><button :disabled="busy" @click="decide('approve')">批准发布</button>
      <button class="secondary" :disabled="busy || !feedback.trim()" @click="decide('request_changes')">要求修改并新建任务</button>
      <button class="secondary" :disabled="busy" @click="decide('reject')">拒绝发布</button></div>
    <p class="mono">草稿 {{ review.draft_hash }}</p>
  </section><p v-if="error" role="alert" class="error">{{ error }}</p>
</template>
