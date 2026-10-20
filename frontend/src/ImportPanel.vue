<script setup>
// 文件直接发送本机 API；服务端校验并整体回滚，不在浏览器推断市场事实。
import { ref } from 'vue'
import { api } from './api'
const emit = defineEmits(['imported'])
const files = {}
const result = ref(null)
const error = ref('')
const busy = ref(false)
function choose(name, event) { files[name] = event.target.files[0] }
async function upload() {
  busy.value = true; error.value = ''
  try {
    const body = new FormData()
    for (const [key, file] of Object.entries(files)) if (file) body.append(key, file)
    result.value = await api('/api/imports/files', { method: 'POST', body })
    emit('imported')
  } catch (err) { error.value = err.message }
  finally { busy.value = false }
}
async function sample() {
  error.value = ''; busy.value = true
  try { result.value = await api('/api/imports/sample', { method: 'POST' }); emit('imported') }
  catch (err) { error.value = err.message }
  finally { busy.value = false }
}
</script>
<template>
  <section class="card">
    <h2>导入商品与研究资料</h2>
    <p class="hint">UTF-8 编码，每份最多 5 MiB。商品和评论使用 CSV，规则使用 JSONL；字段见样例文档。相同编号不同内容会被拒绝。</p>
    <form @submit.prevent="upload">
      <div class="fields">
        <label>商品 CSV<input type="file" accept=".csv" @change="choose('products', $event)"></label>
        <label>评论 CSV<input type="file" accept=".csv" @change="choose('reviews', $event)"></label>
        <label>规则 JSONL<input type="file" accept=".jsonl" @change="choose('rules', $event)"></label>
      </div>
      <div class="actions"><button :disabled="busy">校验并导入</button><button type="button" class="secondary" :disabled="busy" @click="sample">导入内置样例</button></div>
    </form>
    <p v-if="result" class="success">批次 {{ result.batch_id }} · {{ result.status }}<br>商品 {{ result.products }} / 评论 {{ result.reviews }} / 规则 {{ result.rules }}</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p class="hint">导入后需由索引分发器同步向量，固定流程可直接读取数据库。</p>
  </section>
</template>
