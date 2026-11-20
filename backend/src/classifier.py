import numpy as np
from sqlalchemy import select
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.svm import SVC
from sklearn.metrics import confusion_matrix,accuracy_score
from .models import ReferenceSheet,PrintJob
from .constants import DEFECT_TYPES,UNKNOWN

# 正例置信门槛：旧单标签参考漏标的另一类不进训练，留出验证显示其概率明显低于真实正例，
# 低于该门槛的正例倾向不强行断言，按“未知区”抑制，避免把漏标误报成缺陷。
DEFECT_CONFIDENCE_THRESHOLD=.9

def vector(p,target=1.4):return [p.density_c/target,p.density_m/target,p.density_y/target,p.density_k/target,p.dot_gain/100]

def _binary_target(ref,defect_type):
    # 旧参考张只标记一种缺陷：漏标的另一类视为未知(-1)，既不当负例也不参与该类评估
    if defect_type in (ref.defects or []):return 1
    if ref.label=='合格':return 0
    return -1

def classify(s,p):
    refs=s.scalars(select(ReferenceSheet).order_by(ReferenceSheet.id)).all()
    if len(refs)<60:raise ValueError('带标签参考色标不足60张')
    for t in DEFECT_TYPES:
        if sum(1 for r in refs if t in (r.defects or []))<10:raise ValueError(f'参考色标中{t}正例不足10张')
    if sum(1 for r in refs if r.label=='合格')<10:raise ValueError('参考色标中合格正例不足10张')
    x=np.array([vector(r)for r in refs])
    ids=np.arange(len(refs))
    # 按整张分层：四类多标签组合各成一层，训练/留出互斥，同一张不会同时出现在两侧
    strata=[tuple(int(t in (r.defects or []))for t in DEFECT_TYPES)for r in refs]
    train,test=train_test_split(ids,test_size=.2,stratify=strata,random_state=42)
    target=s.get(PrintJob,p.job_id).target_density
    query=[vector(p,target)]
    predicted=[];raw_probabilities={};accepted_flags={};per_type={}
    for t in DEFECT_TYPES:
        y_all=np.array([_binary_target(r,t)for r in refs])
        fit_mask=y_all[train]>=0
        model=make_pipeline(StandardScaler(),SVC(kernel='rbf',C=2,probability=True,random_state=42))
        model.fit(x[train][fit_mask],y_all[train][fit_mask])
        classes=list(model[-1].classes_);pos=classes.index(1)
        prob1=round(float(model.predict_proba(query)[0][pos]),5)
        raw_probabilities[t]=prob1;accepted=prob1>=DEFECT_CONFIDENCE_THRESHOLD;accepted_flags[t]=accepted
        if accepted:predicted.append(t)
        # 留出评估：仅评估标签明确(0/1)的整张贴，按同一置信门槛判正例；漏标项(-1)只统计误报
        eval_mask=y_all[test]>=0
        test_proba=model.predict_proba(x[test][eval_mask])[:,pos]
        pred_test=(test_proba>=DEFECT_CONFIDENCE_THRESHOLD).astype(int)
        y_test=y_all[test][eval_mask]
        cm=confusion_matrix(y_test,pred_test,labels=[0,1]).tolist()
        unknown_idx=test[y_all[test]==-1]
        unknown_proba=model.predict_proba(x[unknown_idx])[:,pos]if len(unknown_idx)else np.array([])
        unknown_hits=int((unknown_proba>=DEFECT_CONFIDENCE_THRESHOLD).sum())if len(unknown_idx)else 0
        per_type[t]={'confusion_matrix':cm,'accuracy':round(float(accuracy_score(y_test,pred_test)),4),
                     'evaluated_rows':int(eval_mask.sum()),'unknown_rows':int(len(unknown_idx)),
                     'unknown_positive_hits':unknown_hits,
                     'unknown_max_probability':round(float(unknown_proba.max()),5)if len(unknown_idx)else None,
                     'unknown_legacy':sorted({refs[i].label for i in unknown_idx}),
                     'threshold':DEFECT_CONFIDENCE_THRESHOLD}
    label='、'.join(predicted)if predicted else '合格'
    holdout_strata={}
    for i in test:
        key='+'.join(t for t,flag in zip(DEFECT_TYPES,strata[i])if flag)or'合格'
        holdout_strata[key]=holdout_strata.get(key,0)+1
    evidence={'probabilities':raw_probabilities,'accepted':accepted_flags,'multi_labels':list(DEFECT_TYPES),
              'unknown_label':UNKNOWN,'confidence_threshold':DEFECT_CONFIDENCE_THRESHOLD,
              'predicted_defects':predicted,'display_label':label,'per_type':per_type,
              'holdout_strata':holdout_strata,
              'train_rows':len(train),'holdout_rows':len(test),'seed':42,
              'reference_codes':[refs[i].code for i in train],'holdout_codes':[refs[i].code for i in test],
              'legacy_label_counts':{k:sum(1 for r in refs if r.label==k)for k in ('合格','乳化','偏色')},
              'multi_label_sheets':sum(1 for r in refs if len(r.defects or [])>1),
              'current_proof_code':p.code,
              'feature_names':['青密度比','品红密度比','黄密度比','黑密度比','网点扩大率'],
              'features':vector(p,target)}
    return label,evidence
