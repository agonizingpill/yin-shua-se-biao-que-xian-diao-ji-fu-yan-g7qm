from sqlalchemy import String,Integer,Float,Boolean,ForeignKey,JSON,CheckConstraint
from sqlalchemy.orm import Mapped,mapped_column
from .db import Base
class User(Base):
    __tablename__='users'
    id:Mapped[int]=mapped_column(primary_key=True)
    email:Mapped[str]=mapped_column(String(100),unique=True)
    password_hash:Mapped[str]=mapped_column(String(180))
    role:Mapped[str]=mapped_column(String(20))
class PrintJob(Base):
    __tablename__='print_jobs'
    __table_args__=(CheckConstraint('target_density > 0'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    code:Mapped[str]=mapped_column(String(40),unique=True)
    title:Mapped[str]=mapped_column(String(100))
    paper:Mapped[str]=mapped_column(String(80))
    target_density:Mapped[float]=mapped_column(Float)
    status:Mapped[str]=mapped_column(String(20),default='setup')
class ProofSheet(Base):
    __tablename__='proof_sheets'
    __table_args__=(CheckConstraint('density_c >= 0 AND density_m >= 0 AND density_y >= 0 AND density_k >= 0 AND dot_gain >= 0'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    job_id:Mapped[int]=mapped_column(ForeignKey('print_jobs.id'))
    code:Mapped[str]=mapped_column(String(40),unique=True)
    density_c:Mapped[float]=mapped_column(Float)
    density_m:Mapped[float]=mapped_column(Float)
    density_y:Mapped[float]=mapped_column(Float)
    density_k:Mapped[float]=mapped_column(Float)
    dot_gain:Mapped[float]=mapped_column(Float)
    # defect 保留为展示用主标签（多缺陷时以“、”连接，无缺陷为合格）
    defect:Mapped[str|None]=mapped_column(String(40),nullable=True)
    # 多标签权威结果：如 ["乳化","偏色"]，无缺陷为 []
    defects:Mapped[list|None]=mapped_column(JSON,nullable=True)
    pass_flag:Mapped[bool]=mapped_column(Boolean,default=False)
    classification_state:Mapped[str]=mapped_column(String(20),default='unmeasured')
    classified_at:Mapped[str|None]=mapped_column(String(40),nullable=True)
    evidence:Mapped[dict|None]=mapped_column(JSON,nullable=True)
class Adjustment(Base):
    __tablename__='adjustments'
    id:Mapped[int]=mapped_column(primary_key=True)
    job_id:Mapped[int]=mapped_column(ForeignKey('print_jobs.id'))
    proof_id:Mapped[int]=mapped_column(ForeignKey('proof_sheets.id'),unique=True)
    ink_delta:Mapped[float]=mapped_column(Float,default=0)
    water_delta:Mapped[float]=mapped_column(Float,default=0)
    status:Mapped[str]=mapped_column(String(20),default='issued')
    executed_at:Mapped[str|None]=mapped_column(String(40),nullable=True)
    reproof_id:Mapped[int|None]=mapped_column(ForeignKey('proof_sheets.id'),nullable=True)
    signed_by:Mapped[str|None]=mapped_column(String(100),nullable=True)
    # 首张判出的缺陷清单快照，逐项处置以此为准
    defects:Mapped[list]=mapped_column(JSON,default=list)
    # 已送验但被中途补做处置作废的复验张（迟回合格也另取）
    invalidated_reproof_ids:Mapped[list]=mapped_column(JSON,default=list)
class AdjustmentAction(Base):
    """逐项处置：每个缺陷一行，先逐项登记执行，再收新复验张。"""
    __tablename__='adjustment_actions'
    id:Mapped[int]=mapped_column(primary_key=True)
    adjustment_id:Mapped[int]=mapped_column(ForeignKey('adjustments.id'))
    defect_type:Mapped[str]=mapped_column(String(20))
    ink_delta:Mapped[float]=mapped_column(Float,default=0)
    water_delta:Mapped[float]=mapped_column(Float,default=0)
    status:Mapped[str]=mapped_column(String(20),default='issued')
    executed_at:Mapped[str|None]=mapped_column(String(40),nullable=True)
    executed_by:Mapped[str|None]=mapped_column(String(100),nullable=True)
class ReproofAttempt(Base):
    """签印尝试登记：以签印当下已登记（已执行）的处置为准判定复验张是否失效。"""
    __tablename__='reproof_attempts'
    id:Mapped[int]=mapped_column(primary_key=True)
    adjustment_id:Mapped[int]=mapped_column(ForeignKey('adjustments.id'))
    proof_id:Mapped[int]=mapped_column(ForeignKey('proof_sheets.id'))
    state:Mapped[str]=mapped_column(String(20),default='attempted')  # attempted / accepted / stale / rejected
    detail:Mapped[str]=mapped_column(String(300),default='')
    created_at:Mapped[str]=mapped_column(String(40))
class ReferenceSheet(Base):
    __tablename__='reference_sheets'
    id:Mapped[int]=mapped_column(primary_key=True)
    code:Mapped[str]=mapped_column(String(40),unique=True)
    density_c:Mapped[float]=mapped_column(Float)
    density_m:Mapped[float]=mapped_column(Float)
    density_y:Mapped[float]=mapped_column(Float)
    density_k:Mapped[float]=mapped_column(Float)
    dot_gain:Mapped[float]=mapped_column(Float)
    # 旧单标签（参考张分别只标记一种缺陷），仅作展示与未知口径证据
    label:Mapped[str]=mapped_column(String(20))
    # 多标签：单标签参考只含自身类型；“乳化+偏色”参考两类都标
    defects:Mapped[list]=mapped_column(JSON,default=list)
class Audit(Base):
    __tablename__='audits'
    id:Mapped[int]=mapped_column(primary_key=True)
    actor:Mapped[str]=mapped_column(String(100))
    action:Mapped[str]=mapped_column(String(200))
    stamp:Mapped[str]=mapped_column(String(40))
