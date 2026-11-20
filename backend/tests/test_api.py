"""HTTP 层集成验证：TestClient + SQLite + 假 Redis（同步执行 worker 判读）。

运行：cd backend && PYTHONPATH=/tmp/pydeps/site:. python3 -m tests.test_api
"""
import os,random,tempfile
from datetime import date
_dbf=os.path.join(tempfile.mkdtemp(),'api-test.db')
os.environ.setdefault('DATABASE_URL','sqlite:///'+_dbf)
os.environ.setdefault('REDIS_URL','redis://localhost:6379/0')
os.environ.setdefault('SEED_DEMO','false')
os.environ.setdefault('ARTIFACT_DIR',tempfile.mkdtemp())

import sqlalchemy.orm.query as _q
_q.Query.with_for_update=lambda self,*a,**k:self  # SQLite 无行锁

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import src.db as db
_test_engine=create_engine('sqlite:///'+_dbf,connect_args={'timeout':30})
_TestSession=sessionmaker(_test_engine,expire_on_commit=False)
db.engine=_test_engine;db.Session=_TestSession

from fastapi.testclient import TestClient
from sqlalchemy import select
from src.db import Base,engine,Session
from src.models import User,ReferenceSheet
from src.dispatch_models import PressMachine,PressInspection
from src.production_models import PlateSet
from src.auth import hash_password
from src.worker import process_proof
import src.main as main
main.engine=_test_engine
import src.production_routes as production_routes

class FakeRedis:
    def rpush(self,key,proof_id):
        with Session()as s:process_proof(s,int(proof_id))
    def ping(self):return True
main.r=FakeRedis();production_routes.queue=FakeRedis()

MEANS={'合格':[1.4,1.4,1.4,1.4,14],'乳化':[1.02,1.04,1.0,1.05,28],
       '偏色':[1.7,1.1,1.55,1.4,15],'乳化+偏色':[1.24,1.06,1.46,1.27,23]}
PASS=0;FAIL=0
def check(name,cond,extra=''):
    global PASS,FAIL
    if cond:PASS+=1;print('  ok -',name)
    else:FAIL+=1;print('  FAIL -',name,extra)

def seed_refs(s):
    rng=random.Random(7);i=0
    for label,n in [('合格',50),('乳化',50),('偏色',50)]:
        for _ in range(n):
            vals=[round(rng.gauss(m,.028 if j<4 else 1),4)for j,m in enumerate(MEANS[label])]
            s.add(ReferenceSheet(code=f'R{i}',density_c=vals[0],density_m=vals[1],density_y=vals[2],density_k=vals[3],dot_gain=vals[4],label=label,defects=[]if label=='合格'else[label]));i+=1
    for _ in range(40):
        vals=[round(rng.gauss(m,.028 if j<4 else 1),4)for j,m in enumerate(MEANS['乳化+偏色'])]
        s.add(ReferenceSheet(code=f'R{i}',density_c=vals[0],density_m=vals[1],density_y=vals[2],density_k=vals[3],dot_gain=vals[4],label='乳化+偏色',defects=['乳化','偏色']));i+=1

with Session()as s:
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    s.add(User(email='admin@x',role='admin',password_hash=hash_password('pw')))
    s.add(User(email='man@x',role='pressman',password_hash=hash_password('pw')))
    s.add(User(email='view@x',role='viewer',password_hash=hash_password('pw')))
    seed_refs(s);s.commit()

c=TestClient(main.app)
tok=c.post('/auth/login',json={'email':'admin@x','password':'pw'}).json()['token']
H={'Authorization':'Bearer '+tok}
def call(method,path,**kw):
    return c.request(method,path,headers=H,**kw)

print('[A] 多标签判读 + 逐项处置接口')
jid=call('POST','/jobs',json={'code':'J1','title':'t','paper':'157g 哑粉','target_density':1.4}).json()['id']
with Session()as s:
    m=PressMachine(code='P1');s.add(m);s.flush()
    s.add(PressInspection(job_id=jid,machine_id=m.id,inspection_date=date.today(),lubricated=True,guards_checked=True,state='approved'))
    s.add(PlateSet(job_id=jid,version='V1',source_note='定稿',registration_error_mm=.08,state='ready',approved_by='admin@x'));s.commit()

def add_proof(code,vals):
    p=call('POST','/proofs',json={'job_id':jid,'code':code,**dict(zip(['density_c','density_m','density_y','density_k','dot_gain'],vals))}).json()
    r=call('POST',f"/proofs/{p['id']}/classify")
    assert r.status_code==200,r.text
    return c.request('GET','/proofs',headers=H).json()

proofs=add_proof('PS-BOTH',MEANS['乳化+偏色'])
pb=[p for p in proofs if p['code']=='PS-BOTH'][0]
check('双缺陷判读返回两类',set(pb['defects'])=={'乳化','偏色'},pb['defects'])
check('证据含逐类核验与门槛',pb['evidence']['confidence_threshold']==.9 and '乳化' in pb['evidence']['per_type'])

# 执行前先取一张合格张（判读时间早于后续执行）
proofs=add_proof('PS-EARLY',MEANS['合格'])
early=[p for p in proofs if p['code']=='PS-EARLY'][0]
check('执行前合格张 pass_flag',early['pass_flag'] is True)

r=call('POST','/adjustments',json={'proof_id':pb['id']});check('生成调机单 200',r.status_code==200,r.text)
adj=r.json();aid=adj['id']
check('视图含两个处置项',len(adj['actions'])==2 and {x['defect_type']for x in adj['actions']}=={'乳化','偏色'})
check('默认处置值正确',{x['defect_type']:(x['ink_delta'],x['water_delta'])for x in adj['actions']}=={'乳化':(0,-8),'偏色':(-6,0)})

em=[x for x in adj['actions']if x['defect_type']=='乳化'][0]
r=call('PATCH',f"/adjustments/actions/{em['id']}",json={'ink_delta':0,'water_delta':3})
check('乳化增水被 409 拒绝',r.status_code==409,r.status_code)

r=call('POST',f"/adjustments/actions/{em['id']}/execute")
check('第一项执行 200',r.status_code==200,r.text)
view=r.json();check('仅一项执行时调机单仍 issued',view['status']=='issued')
r=call('POST',f'/adjustments/{aid}/sign',json={'reproof_id':early['id']})
check('未全部执行签印 409',r.status_code==409)

co=[x for x in view['actions']if x['defect_type']=='偏色'][0]
r=call('POST',f"/adjustments/actions/{co['id']}/execute");check('第二项执行 200',r.status_code==200,r.text)
check('两项执行后 executed',r.json()['status']=='executed')

print('[B] 失效复验与另取签印')
r=call('POST',f'/adjustments/{aid}/sign',json={'reproof_id':early['id']})
check('执行前判读的复验张被拒(失效语义)',r.status_code==409 and '失效' in r.json()['detail'],r.text)
view=call('GET','/adjustments').json();v=[x for x in view if x['id']==aid][0]
check('失效张留痕 invalidated',[x['code']for x in v['invalidated_reproofs']]==['PS-EARLY'])
check('stale 尝试已登记',[x['state']for x in v['reproof_attempts']]==['stale'],v['reproof_attempts'])

proofs=add_proof('PS-NEW',MEANS['合格']);new=[p for p in proofs if p['code']=='PS-NEW'][0]
r=call('POST',f'/adjustments/{aid}/sign',json={'reproof_id':new['id']})
check('新合格复验张签印 200',r.status_code==200,r.text)
job=[j for j in call('GET','/jobs').json()if j['id']==jid][0]
check('工单进入 production',job['status']=='production')
v=[x for x in call('GET','/adjustments').json()if x['id']==aid][0]
check('尝试留痕含 accepted',v['reproof_attempts'][-1]['state']=='accepted')

print('[C] 权限与枚举')
vtok=c.post('/auth/login',json={'email':'view@x','password':'pw'}).json()['token']
r=c.request('POST',f"/adjustments/actions/{em['id']}/execute",headers={'Authorization':'Bearer '+vtok})
check('观察员执行处置 403',r.status_code==403)
en=call('GET','/enums').json()
check('枚举保持旧三类+状态',en['defects']==['合格','乳化','偏色'] and 'signed' in en['adjustment_states'])

print(f'\n{PASS} passed, {FAIL} failed')
raise SystemExit(1 if FAIL else 0)
