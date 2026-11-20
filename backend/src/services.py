from datetime import datetime,timezone
from sqlalchemy import select,or_
from fastapi import HTTPException
from .models import PrintJob,ProofSheet,Adjustment,AdjustmentAction,ReproofAttempt,Audit
from .constants import DEFAULT_DELTAS

def now():return datetime.now(timezone.utc).isoformat()
def get(s,cls,id):
    v=s.get(cls,id)
    if not v:raise HTTPException(404,'记录不存在')
    return v
def pack(v):return {c.name:getattr(v,c.name)for c in v.__table__.columns}
def audit(s,u,action):s.add(Audit(actor=u.email,action=action,stamp=now()))
def editable_proof(s,p):
    if p.classification_state=='classifying':raise HTTPException(409,'判读进行中，色标暂不可修改')
    if get(s,PrintJob,p.job_id).status in ['production','hold']:raise HTTPException(409,'已签印量产工单，色标已冻结')
    if s.scalar(select(Adjustment.id).where(or_(Adjustment.proof_id==p.id,Adjustment.reproof_id==p.id))):raise HTTPException(409,'已关联调机或签印，源色标冻结')

def _actions(s,a):return s.scalars(select(AdjustmentAction).where(AdjustmentAction.adjustment_id==a.id).order_by(AdjustmentAction.id)).all()
def _sync(a,s):
    # 汇总各项处置；全部执行后调机单才进入 executed
    acts=_actions(s,a)
    a.ink_delta=sum(x.ink_delta for x in acts);a.water_delta=sum(x.water_delta for x in acts)
    done=[x for x in acts if x.status=='executed']
    if len(done)==len(acts):
        a.status='executed';a.executed_at=max(x.executed_at for x in done)
    else:
        a.status='issued';a.executed_at=None

def _guards(s,job_id):
    from .plate_service import require_ready
    from .inspection_service import ready
    require_ready(s,job_id);ready(s,job_id)

def issue(s,proof_id):
    p=get(s,ProofSheet,proof_id);job=get(s,PrintJob,p.job_id)
    if job.status in ['production','hold']:raise HTTPException(409,'量产或停机工单须使用抽检/停机复验流程')
    if p.classification_state!='classified' or not p.defects:raise HTTPException(409,'仅已判读的不合格色标可生成调机指令')
    if s.scalar(select(Adjustment.id).where(Adjustment.job_id==job.id,Adjustment.status!='signed')):raise HTTPException(409,'本工单已有未闭合调机，请先完成复验')
    a=Adjustment(job_id=job.id,proof_id=p.id,defects=list(p.defects),status='issued',invalidated_reproof_ids=[]);s.add(a);s.flush()
    for t in a.defects:
        ink,water=DEFAULT_DELTAS[t]
        s.add(AdjustmentAction(adjustment_id=a.id,defect_type=t,ink_delta=ink,water_delta=water))
    s.flush();_sync(a,s);job.status='adjusting';return a

def change_instruction(s,a,data):
    # 旧整体修订入口：仅单缺陷调机单保留；多缺陷请逐项修订
    acts=[x for x in _actions(s,a)if x.status=='issued']
    if not acts:raise HTTPException(409,'处置均已执行，指令冻结')
    if len(_actions(s,a))>1:raise HTTPException(409,'本调机单含多项处置，请逐项修订')
    _apply_change(acts[0],data);_sync(a,s)

def change_action(s,act,data):
    if act.status!='issued':raise HTTPException(409,'该缺陷处置已执行并冻结；补做其余处置会使已送验张失效')
    _apply_change(act,data)
    a=get(s,Adjustment,act.adjustment_id);_sync(a,s)

def _apply_change(act,data):
    if act.defect_type=='乳化'and data.water_delta>=0:raise HTTPException(409,'乳化须减供水，调水量必须为负')
    if act.defect_type=='偏色'and data.ink_delta==0:raise HTTPException(409,'偏色调机须有非零供墨修订')
    act.ink_delta=data.ink_delta;act.water_delta=data.water_delta

def execute_action(s,act,user):
    a=s.query(Adjustment).filter_by(id=act.adjustment_id).with_for_update().one()
    s.query(PrintJob).filter_by(id=a.job_id).with_for_update().one()
    _guards(s,a.job_id)
    if act.status!='issued':raise HTTPException(409,'该处置已登记执行，不能重复执行')
    act.status='executed';act.executed_at=now();act.executed_by=user.email
    _sync(a,s);return a

def execute_all(s,a,user):
    s.query(PrintJob).filter_by(id=a.job_id).with_for_update().one()
    _guards(s,a.job_id)
    pending=[x for x in _actions(s,a)if x.status=='issued']
    if not pending:raise HTTPException(409,'没有待执行的处置项')
    stamp=now()
    for x in pending:x.status='executed';x.executed_at=stamp;x.executed_by=user.email
    _sync(a,s);return a

def adjustment_view(s,a):
    v=pack(a)
    v['actions']=[pack(x)for x in _actions(s,a)]
    attempts=s.scalars(select(ReproofAttempt).where(ReproofAttempt.adjustment_id==a.id).order_by(ReproofAttempt.id)).all()
    v['reproof_attempts']=[{**pack(x),'proof_code':get(s,ProofSheet,x.proof_id).code}for x in attempts]
    v['invalidated_reproofs']=[{'id':i,'code':get(s,ProofSheet,i).code}for i in (a.invalidated_reproof_ids or [])]
    return v

def sign(s,aid,reproof_id,user):
    # 先锁调机单：补做执行与签印并发时，以签印当下已提交登记的处置为准
    a=s.query(Adjustment).filter_by(id=aid).with_for_update().one_or_none()
    if not a:raise HTTPException(404,'调机指令不存在')
    if a.status!='executed':raise HTTPException(409,'请先逐项登记全部缺陷处置的执行；已签印不能重复签印')
    job=s.query(PrintJob).filter_by(id=a.job_id).with_for_update().one()
    if job.status!='adjusting':raise HTTPException(409,'工单不在待复验状态')
    p=get(s,ProofSheet,reproof_id)
    def attempt(state,detail):
        s.add(ReproofAttempt(adjustment_id=a.id,proof_id=p.id,state=state,detail=detail,created_at=now()))
    if p.id==a.proof_id or p.job_id!=job.id:
        attempt('rejected','复验张必须来自同一工单且不同于首张');s.commit();raise HTTPException(409,'复验张必须来自同一工单且不同于首张')
    if p.classification_state!='classified'or not p.pass_flag or p.defect!='合格':
        attempt('rejected','复验张未判为合格');s.commit();raise HTTPException(409,'复验张未判为合格，禁止恢复量产')
    # 以签印当下已登记的处置执行时间为准：判读早于最后一次执行，即已被补做处置作废
    latest=max(x.executed_at for x in _actions(s,a)if x.status=='executed')
    if not p.classified_at or p.classified_at<latest:
        if p.id not in (a.invalidated_reproof_ids or []):a.invalidated_reproof_ids=[*(a.invalidated_reproof_ids or []),p.id]
        attempt('stale','判读早于最新处置执行，已送验张失效，须另取新复验张');s.commit()
        raise HTTPException(409,'该复验张判读后又有补做处置登记，已失效；即使迟回合格也须另取新复验张')
    from .plate_service import require_ready
    require_ready(s,job.id)
    attempt('accepted','两项缺陷处置后复验合格')
    a.reproof_id=p.id;a.status='signed';a.signed_by=user.email;job.status='production';return a
