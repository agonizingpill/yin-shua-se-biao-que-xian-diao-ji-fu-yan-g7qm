import os,json,logging
from pathlib import Path
import redis
from .db import Session
from .models import ProofSheet
from .classifier import classify
from .services import now
from .sampling_service import finish
r=redis.Redis.from_url(os.environ['REDIS_URL'],decode_responses=True);ARTIFACT_DIR=Path(os.environ.get('ARTIFACT_DIR','/artifacts'));ARTIFACT_DIR.mkdir(parents=True,exist_ok=True)

def process_proof(s,proof_id):
    p=s.get(ProofSheet,proof_id)
    if not p or p.classification_state!='classifying':return
    try:
        p.defect,p.evidence=classify(s,p)
        p.defects=list(p.evidence['predicted_defects'])
        p.pass_flag=not p.defects
        p.classification_state='classified';p.classified_at=now();finish(s,p);s.commit()
        Path(ARTIFACT_DIR,f'proof-{p.id}.json').write_text(json.dumps(p.evidence,ensure_ascii=False))
    except Exception as ex:
        s.rollback();p=s.get(ProofSheet,proof_id)
        p.classification_state='failed';p.evidence={'error':str(ex)};finish(s,p);s.commit();logging.exception('classification failed')

def main():
    while True:
        Path('/tmp/worker-heartbeat').touch();entry=r.blpop('press-classify',timeout=2)
        if not entry:continue
        with Session()as s:process_proof(s,int(entry[1]))

if __name__=='__main__':main()
