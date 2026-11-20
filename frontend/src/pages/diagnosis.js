import {esc,localStamp} from '../utils/format.js';
import {proof} from '../store.js';
import {proofPicker,empty,notify,jobLabel} from '../components/press.js';
import {send} from '../api.js';
import {CONFIDENCE_THRESHOLD,UNKNOWN} from '../constants.js';

const probRow=(name,v,accepted)=>`<div class="prob"><div class="label"><span>${esc(name)}${accepted?'':' <small class="unk">（低于门槛，按未知抑制）</small>'}</span><span class="mono">${(v*100).toFixed(2)}%${accepted?'':' / 未知区'}</span></div><div class="bar"><span style="width:${Math.min(v,1)*100}%;${accepted?'':'background:var(--cyan)'}"></span></div></div>`;

export function render(s){
  const p=proof(s),r=p?.evidence;
  const probs=r?.probabilities,accepted=r?.accepted;
  return `<div class="head"><div><div class="eyebrow">DEFECT READING / 03</div><h1>一张色标，两类缺陷分别判。</h1><p>${p?jobLabel(s,p.job_id):'选择色标'} / ${p?esc(p.code):''}</p></div><div class="picker">${proofPicker(s)}</div></div>${p?`<div class="diagnostic"><section class="section"><h2>四色密度读数</h2>
  <div class="cmyk">${['c','m','y','k'].map(k=>`<div class="patch">${Number(p['density_'+k]).toFixed(2)}<small>${k.toUpperCase()} / 色标密度</small></div>`).join('')}</div>
  <div class="metricstrip"><div>网点扩大率<b>${p.dot_gain}%</b></div><div>判读时间<b style="font-size:12px">${p.classified_at?esc(localStamp(p.classified_at)):'待判读'}</b></div></div>
  ${p.defect?`<div class="defecttitle">${esc(p.defect)}</div>
    ${(p.defects||[]).length?`<p class="note">本张同时判出 ${p.defects.map(esc).join('、')}，调机页将逐缺陷生成处置，两项都合格才可签印。</p>`:'<p class="note">两类缺陷置信度均未达门槛，判为合格。</p>'}
    <h3>逐缺陷二分类概率（门槛 ${(CONFIDENCE_THRESHOLD*100).toFixed(0)}%）</h3>
    ${probs?Object.entries(probs).map(([k,v])=>probRow(k,v,accepted?accepted[k]:true)).join(''):'<p class="muted">旧版判读证据，请重新读取缺陷以生成逐缺陷概率。</p>'}
    <p class="muted">旧参考张每张只标记一种缺陷，漏标的另一类在该分类器中按“${UNKNOWN}”处理：既不当负例训练，也不参与准确率统计，仅在右侧核验中观察其误报。</p>`
  :empty(r?.error||'色标尚未判读。点击读取缺陷，后台将对乳化、偏色各训练一个二分类 SVM，返回逐缺陷概率。')}
  <div class="actions"><button id="classify" class="primary" ${s.user.role==='viewer'||p.classification_state==='classifying'?'disabled':''}>${p.classification_state==='classifying'?'正在读取色标…':'读取缺陷'}</button>
  <button id="issue-adjustment" class="magenta" ${s.user.role==='viewer'||!p.defect||p.pass_flag?'disabled':''}>按缺陷生成调机指令</button></div>
  <p class="note">乳化优先减供水，偏色修订供墨；双缺陷张会一次生成两项处置。合格色标作为复验依据，主管须在全部处置执行后确认同工单合格复验张。</p></section>
  <aside class="section"><h2>按整张留出的逐类核验</h2>${r?.per_type?`<p class="muted">行是真实标签，列是预测；同一张参考整张贴要么进训练、要么进留出，不会同时出现在两侧。</p>
    ${Object.entries(r.per_type).map(([t,m])=>`<div class="per-type"><h3>${esc(t)}二分类（训练正例含双缺陷张）</h3>
      <table class="matrix small"><thead><tr><th>真实 / 预测</th><th>无${esc(t)}</th><th>有${esc(t)}</th></tr></thead><tbody>
      <tr><th>无${esc(t)}</th>${m.confusion_matrix[0].map((v,j)=>`<td class="${j===0?'diag':''}">${v}</td>`).join('')}</tr>
      <tr><th>有${esc(t)}</th>${m.confusion_matrix[1].map((v,j)=>`<td class="${j===1?'diag':''}">${v}</td>`).join('')}</tr></tbody></table>
      <div class="metricstrip"><div>评估整张贴<b>${m.evaluated_rows}</b></div><div>留出准确率<b>${(m.accuracy*100).toFixed(1)}%</b></div><div>漏标${UNKNOWN}张<b>${m.unknown_rows}</b></div><div>${UNKNOWN}误报<b>${m.unknown_positive_hits}</b></div></div>
      <p class="muted">漏标${UNKNOWN}行（旧标签：${(m.unknown_legacy||[]).join('、')||'—'}）最高正例概率 ${m.unknown_max_probability==null?'—':(m.unknown_max_probability*100).toFixed(1)+'%'}，门槛 ${(m.threshold*100).toFixed(0)}% 下不强行断言。</p></div>`).join('')}
    <div class="metricstrip"><div>训练 / 留出整张贴<b>${r.train_rows} / ${r.holdout_rows}</b></div><div>双缺陷参考张<b>${r.multi_label_sheets}</b></div></div>
    <p class="muted">留出分层：${Object.entries(r.holdout_strata).map(([k,v])=>`${esc(k)} ${v}张`).join('，')}。概率仅为模型倾向，调机后仍须重新取样复验。</p>`
  :empty('判读完成后显示逐缺陷混淆矩阵、漏标未知行与留出核验。')}</aside></div>`:empty('请先登记一张色标。')}`;
}
export function bind(s,reload){
  document.querySelector('#proof-picker').onchange=async e=>{s.proofId=Number(e.target.value);await reload()};
  const p=proof(s);if(!p)return;
  document.querySelector('#classify').onclick=async()=>{try{await send('/proofs/'+p.id+'/classify');notify('正在读取色标缺陷');await reload()}catch(e){notify(e.message)}};
  document.querySelector('#issue-adjustment').onclick=async()=>{try{const a=await send('/adjustments',{proof_id:p.id});s.adjustmentId=a.id;notify('调机指令已按缺陷逐项生成');location.hash='#adjustments'}catch(e){notify(e.message)}};
}
