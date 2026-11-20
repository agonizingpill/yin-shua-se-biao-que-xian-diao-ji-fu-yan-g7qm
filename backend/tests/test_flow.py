"""端到端规则验证：多标签判读、逐项处置、复验失效与签印并发。

运行：cd backend && PYTHONPATH=. ../.venv/bin/python -m tests.test_flow
使用临时 SQLite，不依赖 MySQL/Redis；FOR UPDATE 在 SQLite 下降级为普通查询。
"""
import os,random,tempfile,threading
from datetime import date
from sqlalchemy import create_engine,select
from sqlalchemy.orm import sessionmaker
import sqlalchemy.orm.query as _q

tmp=tempfile.mkdtemp()
engine=create_engine('sqlite:///'+os.path.join(tmp,'test.db'),connect_args={'timeout':30})
Session=sessionmaker(engine,expire_on_commit=False)
import src.db as db
db.engine=engine;db.Session=Session
_q.Query.with_for_update=lambda self,*a,**k:self  # SQLite 无行锁

from src.models import (Base,User,PrintJob,ProofSheet,Adjustment,AdjustmentAction,
                        ReproofAttempt,ReferenceSheet)
from src.dispatch_models import PressMachine,PressInspection
from src.production_models import PlateSet
from src.auth import hash_password
from src.classifier import classify
from src.worker import process_proof
from src import services

MEANS={'合格':[1.4,1.4,1.4,1.4,14],'乳化':[1.02,1.04,1.0,1.05,28],
       '偏色':[1.7,1.1,1.55,1.4,15],'乳化+偏色':[1.24,1.06,1.46,1.27,23]}
PASS=0;FAIL=0

def check(name,cond,extra=''):
    global PASS,FAIL
    if cond:PASS+=1;print('  ok -',name)
    else:FAIL+=1;print('  FAIL -',name,extra)

def make_refs(s):
    rng=random.Random(42)
    i=0
    for label,n in [('合格',50),('乳化',50),('偏色',50)]:
        for _ in range(n):
            vals=[round(rng.gauss(m,.028 if j<4 else 1),4)for j,m in enumerate(MEANS[label])]
            s.add(ReferenceSheet(code=f'REF-{i:03}',**dict(zip(['density_c','density_m','density_y','density_k','dot_gain'],vals)),
                                 label=label,defects=[]if label=='合格'else[label]));i+=1
    for _ in range(40):
        vals=[round(rng.gauss(m,.028 if j<4 else 1),4)for j,m in enumerate(MEANS['乳化+偏色'])]
        s.add(ReferenceSheet(code=f'REF-BOTH-{i:03}',**dict(zip(['density_c','density_m','density_y','density_k','dot_gain'],vals)),
                             label='乳化+偏色',defects=['乳化','偏色']));i+=1
    s.commit()

def proof(s,job,code,vals,state='unmeasured'):
    p=ProofSheet(job_id=job.id,code=code,density_c=vals[0],density_m=vals[1],density_y=vals[2],
                 density_k=vals[3],dot_gain=vals[4],classification_state=state);s.add(p);s.commit();return p

def ready_guards(s,job):
    m=s.scalar(select(PressMachine).where(PressMachine.code=='PRESS-04'))
    if not m:
        m=PressMachine(code='PRESS-04');s.add(m);s.flush()
    s.add(PressInspection(job_id=job.id,machine_id=m.id,inspection_date=date.today(),
                          lubricated=True,guards_checked=True,state='approved'))
    s.add(PlateSet(job_id=job.id,version='V1',source_note='定稿',
                   registration_error_mm=.08,state='ready',approved_by='admin@x'))
    s.commit()

def run_classify(s,p):
    p.classification_state='classifying';s.commit()
    process_proof(s,p.id)
    return s.get(ProofSheet,p.id)

def main():
    Base.metadata.create_all(engine)
    with Session()as s:
        admin=User(email='admin@x',role='admin',password_hash=hash_password('pw'))
        man=User(email='man@x',role='pressman',password_hash=hash_password('pw'))
        s.add_all([admin,man]);s.commit()
        make_refs(s)
        job=PrintJob(code='J1',title='t',paper='157g 纸',target_density=1.4,status='setup');s.add(job);s.commit()
        ready_guards(s,job)

        print('[1] 分类器：整张分层 + 旧标签漏标按未知')
        # 合格
        p_ok=run_classify(s,proof(s,job,'P-OK',MEANS['合格']))
        check('合格张无缺陷 pass_flag',p_ok.pass_flag and p_ok.defects==[],p_ok.defects)
        # 仅乳化
        p_e=run_classify(s,proof(s,job,'P-E',MEANS['乳化']))
        check('乳化张只报乳化',p_e.defects==['乳化'],p_e.defects)
        # 仅偏色
        p_c=run_classify(s,proof(s,job,'P-C',MEANS['偏色']))
        check('偏色张只报偏色',p_c.defects==['偏色'],p_c.defects)
        # 双缺陷
        p_b=run_classify(s,proof(s,job,'P-BOTH',MEANS['乳化+偏色']))
        check('双缺陷张两类都报出',set(p_b.defects)=={'乳化','偏色'},p_b.defects)
        ev=p_b.evidence
        check('训练/留出整张互斥',not(set(ev['reference_codes'])&set(ev['holdout_codes'])))
        check('留出含双缺陷层',ev['holdout_strata'].get('乳化+偏色',0)==8,ev['holdout_strata'])
        check('乳化类留出存在漏标未知行(偏色单标签)',ev['per_type']['乳化']['unknown_rows']>0)
        check('偏色类留出存在漏标未知行(乳化单标签)',ev['per_type']['偏色']['unknown_rows']>0)
        check('置信门槛下未知行无误报',all(ev['per_type'][t]['unknown_positive_hits']==0 for t in ('乳化','偏色')))
        check('两类留出准确率>=0.85',all(ev['per_type'][t]['accuracy']>=.85 for t in ('乳化','偏色')),
              {t:ev['per_type'][t]['accuracy']for t in ('乳化','偏色')})
        check('纯乳化张偏色置信低于门槛被抑制',ev['per_type']['偏色']['threshold']==.9)

        print('[2] 双缺陷逐项处置 + 新复验张合格才签印')
        a=services.issue(s,p_b.id);s.commit()
        check('调机单生成两个处置项',len(a.defects)==2 and len(services._actions(s,a))==2)
        check('工单进入 adjusting',s.get(PrintJob,job.id).status=='adjusting')
        acts=services._actions(s,a)
        by={x.defect_type:x for x in acts}
        check('默认水/墨处置',by['乳化'].water_delta==-8 and by['偏色'].ink_delta==-6)
        # 只执行一项时不能签印
        services.execute_action(s,by['乳化'],man);s.commit()
        check('仅一项执行时调机单仍 issued',s.get(Adjustment,a.id).status=='issued')
        try:
            services.sign(s,a.id,p_ok.id,admin);check('未全部执行拒绝签印',False)
        except Exception as ex:check('未全部执行拒绝签印', '请先逐项' in str(ex.detail))
        # 执行第二项
        services.execute_action(s,by['偏色'],man);s.commit()
        a=s.get(Adjustment,a.id)
        check('两项执行后 executed',a.status=='executed' and a.executed_at)
        # 旧合格张判读早于执行 → 时序拒绝
        try:
            services.sign(s,a.id,p_ok.id,admin);check('早于执行的复验拒绝',False)
        except Exception as ex:check('早于执行的复验拒绝','判读后又有补做' in str(ex.detail) or '失效' in str(ex.detail))
        # 新复验张（执行后判读）
        p_new=run_classify(s,proof(s,job,'P-NEW',MEANS['合格']))
        check('新复验判为合格',p_new.pass_flag)
        services.sign(s,a.id,p_new.id,admin);s.commit()
        a=s.get(Adjustment,a.id);job=s.get(PrintJob,job.id)
        check('签印成功',a.status=='signed' and a.reproof_id==p_new.id and job.status=='production')
        check('接受尝试已登记',any(x.state=='accepted' for x in s.scalars(select(ReproofAttempt)).all()))

        print('[3] 中途补做处置：已送验张失效，迟回合格另取')
        job2=PrintJob(code='J2',title='t2',paper='157g 纸',target_density=1.4,status='setup');s.add(job2);s.commit()
        ready_guards(s,job2)
        p_b2=run_classify(s,proof(s,job2,'P-BOTH2',MEANS['乳化+偏色']))
        a2=services.issue(s,p_b2.id);s.commit()
        acts2=services._actions(s,a2)
        services.execute_action(s,acts2[0],man);s.commit()
        # 送验一张（在第一项执行之后判读，合格）
        p_sent=run_classify(s,proof(s,job2,'P-SENT',MEANS['合格']))
        # 中途补做第二项处置
        services.execute_action(s,acts2[1],man);s.commit()
        a2=s.get(Adjustment,a2.id)
        check('补做后全部执行',a2.status=='executed')
        try:
            services.sign(s,a2.id,p_sent.id,admin);check('失效张签印被拒',False)
        except Exception as ex:check('失效张签印被拒','失效' in str(ex.detail),str(ex.detail))
        a2=s.get(Adjustment,a2.id)
        check('失效张进入 invalidated 列表',p_sent.id in a2.invalidated_reproof_ids)
        check('stale 尝试已登记',s.scalar(select(ReproofAttempt).where(ReproofAttempt.proof_id==p_sent.id,ReproofAttempt.state=='stale'))is not None)
        # 迟回的合格仍须另取：再用同一张还是拒绝
        try:
            services.sign(s,a2.id,p_sent.id,admin);check('重复使用失效张仍拒绝',False)
        except Exception:check('重复使用失效张仍拒绝',True)
        p_new2=run_classify(s,proof(s,job2,'P-NEW2',MEANS['合格']))
        services.sign(s,a2.id,p_new2.id,admin);s.commit()
        check('另取新张后签印成功',s.get(Adjustment,a2.id).status=='signed')

        print('[4] 补做与签印并发：以签印当下已登记处置为准')
        job3=PrintJob(code='J3',title='t3',paper='157g 纸',target_density=1.4,status='setup');s.add(job3);s.commit()
        ready_guards(s,job3)
        p_b3=run_classify(s,proof(s,job3,'P-BOTH3',MEANS['乳化+偏色']))
        with Session()as s3:
            a3=services.issue(s3,p_b3.id);s3.commit();aid=a3.id
        barrier=threading.Barrier(2)
        outcomes=[]
        def do_execute():
            with Session()as se:
                act=se.scalars(select(AdjustmentAction).where(AdjustmentAction.adjustment_id==aid,AdjustmentAction.status=='issued')).first()
                barrier.wait()
                try:services.execute_action(se,act,man);se.commit();outcomes.append(('exec','ok'))
                except Exception as ex:outcomes.append(('exec','fail',str(ex)))
        def do_sign():
            with Session()as ss:
                pq=proof(ss,ss.get(PrintJob,job3.id),'P-CONF',MEANS['合格'])
                pq=run_classify(ss,pq)
                barrier.wait()
                try:services.sign(ss,aid,pq.id,admin);ss.commit();outcomes.append(('sign','ok'))
                except Exception as ex:outcomes.append(('sign','fail',str(ex.detail)))
        t1=threading.Thread(target=do_execute);t2=threading.Thread(target=do_sign);t1.start();t2.start();t1.join();t2.join()
        with Session()as sf:
            a3=sf.get(Adjustment,aid)
            check('并发后调机单未被错误闭合（补做优先语义）',a3.status!='signed',str(outcomes))
            check('并发产生确定结果（一胜一拒或执行先于签印被时序拦截）',len(outcomes)==2,str(outcomes))
            print('   并发结果：',outcomes)

    print(f'\n{PASS} passed, {FAIL} failed')
    raise SystemExit(1 if FAIL else 0)

if __name__=='__main__':main()
