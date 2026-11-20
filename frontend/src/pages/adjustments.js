import {esc,formData,localStamp} from '../utils/format.js';
import {adjustment} from '../store.js';
import {badge,empty,notify,jobLabel} from '../components/press.js';
import {send} from '../api.js';

const deltaText=a=>`${a.ink_delta>0?'+':''}${a.ink_delta} 墨 / ${a.water_delta>0?'+':''}${a.water_delta} 水`;
const actionCard=(s,a,x)=>`<article class="action-card" data-action="${x.id}">
  <div class="action-head"><b>${esc(x.defect_type)}处置</b>${badge(x.status==='executed'?'executed':'issued',x.status==='executed'?'已执行':'待执行')}</div>
  <p class="muted">${x.defect_type==='乳化'?'降低供水，恢复油墨与润版液平衡，再核对网点扩大。':'按供墨差异修订墨量，确认四色密度回到目标。'}${x.executed_at?'<br>执行 '+esc(localStamp(x.executed_at))+' · '+esc(x.executed_by||''):''}</p>
  <form class="action-form" data-action="${x.id}">
    <div class="formgrid">
      <div><label>供墨调整 / %</label><input name="ink_delta" type="number" min="-15" max="15" step=".5" value="${x.ink_delta}" ${x.status==='executed'||s.user.role==='viewer'?'disabled':''} required></div>
      <div><label>供水调整 / %</label><input name="water_delta" type="number" min="-15" max="15" step=".5" value="${x.water_delta}" ${x.status==='executed'||s.user.role==='viewer'?'disabled':''} required></div>
    </div>
    <div class="actions">
      <button data-act="patch" ${x.status==='executed'||s.user.role==='viewer'?'disabled':''}>修订此项</button>
      <button data-act="execute" class="primary" ${x.status==='executed'||s.user.role==='viewer'?'disabled':''}>登记此项已执行</button>
    </div>
  </form>
</article>`;

const attemptRow=(s,x)=>{const p=s.proofs.find(q=>q.id===x.proof_id);const map={accepted:'接受',stale:'已失效',rejected:'拒收'};
  return `<tr><td class="mono">${esc(p?.code||('#'+x.proof_id))}</td><td><span class="status ${x.state==='accepted'?'pass':x.state==='stale'?'fail':''}">${map[x.state]||x.state}</span></td><td>${esc(x.detail)}</td><td class="mono">${esc(localStamp(x.created_at))}</td></tr>`};

export function render(s){
  const a=adjustment(s),source=s.proofs.find(p=>p.id===a?.proof_id),job=s.jobs.find(j=>j.id===a?.job_id);
  return `<div class="head"><div><div class="eyebrow">ADJUST / RECHECK / SIGN / 04</div><h1>逐项处置，验过两项才签印。</h1><p>先在“印版上机核对”取得就绪版次；双缺陷张的每项处置分别登记执行，全部执行后重新取样，复验张两项都合格主管才可签印。</p></div>
  <div class="picker"><select id="adjustment-picker">${s.adjustments.map(x=>`<option value="${x.id}" ${x.id===Number(s.adjustmentId)?'selected':''}>指令 #${x.id} / ${esc(s.jobs.find(j=>j.id===x.job_id)?.code)} / ${x.status}</option>`).join('')}</select></div></div>
  ${a?`<div class="columns"><section class="instruction">
    <div class="instruction-head"><div><div class="eyebrow">PRESS ADJUSTMENT / ${String(a.id).padStart(3,'0')}</div><h2>${esc(job?.title)}</h2><p class="muted">${jobLabel(s,a.job_id)} / 首张 ${esc(source?.code)} / 判出 ${esc((a.defects||[]).join('、')||source?.defect)}</p></div>${badge(a.status)}</div>
    <div class="bigdelta"><div><small>汇总供墨调整 / %</small><b>${a.ink_delta>0?'+':''}${a.ink_delta}</b></div><div><small>汇总供水调整 / %</small><b>${a.water_delta>0?'+':''}${a.water_delta}</b></div></div>
    <div class="step"><span class="n">01</span><div><b>逐项登记缺陷处置（先处置，后取样）</b><p>每个缺陷一项指令，待执行时可在规则内修订；执行后冻结。中途补做处置会使已送验的复验张失效。</p></div></div>
    <div class="action-list">${(a.actions||[]).map(x=>actionCard(s,a,x)).join('')}</div>
    <div class="actions">
      <button id="execute-all" class="primary" ${s.user.role==='viewer'||a.status==='signed'||!(a.actions||[]).some(x=>x.status==='issued')?'disabled':''}>一次登记全部待执行处置</button>
    </div>
    <div class="step"><span class="n">02</span><div><b>执行后重新取样判读</b><p>${a.executed_at?'最后处置执行时间 '+esc(localStamp(a.executed_at)):'尚有处置未执行，不能用复验张签印。'}<br>去色标录入登记新样张并判读，复验判读须晚于最后一次处置执行；之后再补做处置，已送验张立即失效。</p></div></div>
    <div class="step"><span class="n">03</span><div><b>两项都合格后主管签印</b><p>${a.status==='signed'?'签印人 '+esc(a.signed_by)+' / 复验张 '+esc(s.proofs.find(p=>p.id===a.reproof_id)?.code):'主管以签印当下已登记的处置为准核对复验张，签印后指令闭合、工单进入量产。'}</p></div></div>
  </section>
  <aside class="section">
    <h2>复验与主管签印</h2>
    <div class="checkline"><span>开机单</span>${badge(job?.status)}</div>
    <div class="checkline"><span>处置执行</span><b>${(a.actions||[]).filter(x=>x.status==='executed').length} / ${(a.actions||[]).length} 项</b></div>
    <div class="checkline"><span>首张色标冻结</span><b>${esc(source?.code)}</b></div>
    <form id="sign-form">
      <label>复验色标（须执行后新判合格）</label>
      <select name="reproof_id">${s.proofs.filter(p=>p.id!==a.proof_id).map(p=>`<option value="${p.id}" ${p.id===a.reproof_id?'selected':''} ${(a.invalidated_reproof_ids||[]).includes(p.id)?'data-stale="1"':''}>${esc(p.code)} · ${esc(p.defect||'待判读')} / ${esc(s.jobs.find(j=>j.id===p.job_id)?.code)}${(a.invalidated_reproof_ids||[]).includes(p.id)?'（已失效）':''}</option>`).join('')}</select>
      <div class="actions"><button class="magenta" ${s.user.role!=='admin'||a.status!=='executed'?'disabled':''}>主管签印恢复量产</button></div>
    </form>
    <p class="note">复验必须同工单、判为合格且判读晚于最后处置执行。补做处置后迟回的合格张也须另取；签印与补做并发时，以签印当下已登记的处置为准。</p>
    <h3 style="margin-top:20px">复验尝试留痕</h3>
    <div class="tablewrap"><table><thead><tr><th>色标</th><th>结果</th><th>原因</th><th>时间</th></tr></thead><tbody>
      ${(a.reproof_attempts||[]).length?(a.reproof_attempts||[]).map(x=>attemptRow(s,x)).join(''):'<tr><td colspan="4" class="muted">尚无签印尝试</td></tr>'}
    </tbody></table></div>
    ${(a.invalidated_reproofs||[]).length?`<p class="note">已失效另取：${a.invalidated_reproofs.map(x=>esc(x.code)).join('、')}</p>`:''}
  </aside></div>`
  :empty('尚无调机指令。先在缺陷判读页读取不合格色标，再按缺陷逐项生成指令。')}`;
}
export function bind(s,reload){
  document.querySelector('#adjustment-picker').onchange=async e=>{s.adjustmentId=Number(e.target.value);await reload()};
  const a=adjustment(s);if(!a)return;
  document.querySelectorAll('.action-form').forEach(f=>{
    f.onsubmit=async ev=>{ev.preventDefault();const act=ev.submitter?.dataset.act;const id=Number(f.dataset.action);
      const p=formData(f);p.ink_delta=Number(p.ink_delta);p.water_delta=Number(p.water_delta);
      try{
        if(act==='patch'){await send('/adjustments/actions/'+id,p,'PATCH');notify('该项处置已修订')}
        else{await send('/adjustments/actions/'+id+'/execute');notify('该项处置执行已登记')}
        await reload();
      }catch(e){notify(e.message)}};
  });
  const all=document.querySelector('#execute-all');
  if(all)all.onclick=async()=>{try{await send('/adjustments/'+a.id+'/actions/execute',{action_ids:[]});notify('全部待执行处置已登记');await reload()}catch(e){notify(e.message)}};
  const sf=document.querySelector('#sign-form');
  sf.onsubmit=async ev=>{ev.preventDefault();try{await send('/adjustments/'+a.id+'/sign',{reproof_id:Number(new FormData(ev.target).get('reproof_id'))});notify('复验签印完成，工单已恢复量产');await reload()}catch(e){notify(e.message)}};
}
