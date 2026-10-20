<script setup>
// 有效偏好与模型候选分开显示，候选必须由用户确认。
import { ref, onMounted } from 'vue'
import { api, jsonPost } from './api'
const profile = ref(null), candidates = ref([]), error = ref(''), message = ref('')
async function load() {
  try { profile.value = await api('/api/preferences'); candidates.value = await api('/api/memory-candidates') }
  catch (err) { error.value = err.message }
}
async function save(clear = false) {
  try {
    profile.value = await api('/api/preferences', clear ? {method:'DELETE'} : {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(profile.value.content)})
    message.value = '已保存；后续新任务使用此版本。'
  } catch (err) { error.value = err.message }
}
async function decide(row, action) {
  try { await api(`/api/memory-candidates/${row.id}/decision`, jsonPost({action, content:row.content})); await load() }
  catch (err) { error.value = err.message }
}
onMounted(load)
</script>
<template>
  <section class="card" v-if="profile">
    <h2>个人偏好与候选记忆</h2><p>仅用于本地单用户研究。偏好不会覆盖商品事实；历史报告保留创建时的偏好版本。</p>
    <form @submit.prevent="save(false)">
      <label>目标市场（两位代码，可留空）<input v-model="profile.content.target_market" maxlength="2" placeholder="US"></label>
      <label>排除品类（逗号分隔）<input :value="profile.content.excluded_categories.join(',')" @input="profile.content.excluded_categories = $event.target.value.split(',').map(x=>x.trim()).filter(Boolean)"></label>
      <label>回答语言<input v-model="profile.content.response_language" maxlength="30"></label>
      <div class="actions"><button>保存偏好</button><button type="button" class="secondary" @click="save(true)">清空偏好</button></div>
    </form><p class="hint">当前版本 {{ profile.version }} · {{ message }}</p>
    <h3>待确认候选</h3><p v-if="!candidates.length">暂无候选。模型追问时可选择允许提出偏好建议。</p>
    <article v-for="row in candidates" :key="row.id" class="claim">
      <p>来源问题：{{ row.reason }}</p><small>报告 {{ row.run_id }}</small>
      <label>目标市场<input v-model="row.content.target_market" maxlength="2"></label>
      <label>排除品类<input :value="row.content.excluded_categories.join(',')" @input="row.content.excluded_categories=$event.target.value.split(',').map(x=>x.trim()).filter(Boolean)"></label>
      <label>回答语言<input v-model="row.content.response_language"></label>
      <div class="actions"><button @click="decide(row,'confirm')">确认以上偏好</button><button class="secondary" @click="decide(row,'ignore')">忽略</button></div>
    </article>
  </section><p v-if="error" role="alert" class="error">{{ error }}</p>
</template>
