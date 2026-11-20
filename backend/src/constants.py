ROLES=('admin','pressman','viewer')
# 旧单标签体系：合格 / 乳化 / 偏色，一张参考只报一种
DEFECTS=('合格','乳化','偏色')
# 两类可同时出现的缺陷，按整张开两个独立的二分类器
DEFECT_TYPES=('乳化','偏色')
UNKNOWN='未知'
JOB_STATES=('setup','adjusting','production','hold')
ADJUSTMENT_STATES=('issued','executed','signed')
ACTION_STATES=('issued','executed')
# 各类缺陷的默认处置（百分比，负号表示减少供量）
DEFAULT_DELTAS={'乳化':(0,-8),'偏色':(-6,0)}
