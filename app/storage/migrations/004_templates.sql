-- 纪要模板专业化：场景、说明、自定义展示模块

ALTER TABLE minute_template ADD COLUMN description TEXT NOT NULL DEFAULT '';
ALTER TABLE minute_template ADD COLUMN scene TEXT NOT NULL DEFAULT '常规';
ALTER TABLE minute_template ADD COLUMN custom_sections TEXT NOT NULL DEFAULT '[]';

INSERT OR IGNORE INTO minute_template
 (key, name, sections, hint, builtin, description, scene, custom_sections, updated_at)
VALUES
 ('weekly', '周会',
  '["summary","topics","actions","open_issues"]',
  '模板：周会。先按人/模块归纳本周进展与数据，再输出下周计划、阻塞与需要协调的事项。每条待办必须写明负责人与时间；没有明确负责人的写“待指定”。不要复述寒暄。',
  1, '适合固定周会、站会，突出进展、计划与阻塞。', '周会',
  '[{"key":"progress","title":"本周进展","instruction":"按模块或负责人归纳已完成事项，尽量保留数字与时间"},{"key":"next_plan","title":"下周计划","instruction":"列出下周要做的事、负责人和预计完成时间"},{"key":"blockers","title":"阻塞与协调","instruction":"列出受阻事项、等待对象和需要谁决策"}]',
  datetime('now', 'localtime')),
 ('project_review', '项目复盘',
  '["summary","topics","decisions","actions","open_issues"]',
  '模板：项目复盘。围绕目标、结果、偏差、原因、经验教训组织内容。区分事实与判断，不美化结果；待办要能直接执行，注明负责人与截止时间。',
  1, '适合项目结束或阶段性复盘，沉淀经验与改进项。', '复盘',
  '[{"key":"goals","title":"目标与结果","instruction":"对照原定目标列出实际结果，保留关键指标"},{"key":"gaps","title":"偏差与原因","instruction":"说明未达预期的部分及主要原因，区分主观与客观"},{"key":"lessons","title":"经验教训","instruction":"提炼可复用的做法和需要避免的问题"}]',
  datetime('now', 'localtime')),
 ('decision_review', '决策评审',
  '["summary","topics","decisions","actions","open_issues"]',
  '模板：决策评审。重点还原决策背景、候选方案、评估依据和最终结论。必须区分“已决定”和“待决定”；风险、依赖、反对意见要单独列出，不得含糊。',
  1, '适合方案评审、立项会、采购决策会。', '决策',
  '[{"key":"options","title":"方案对比","instruction":"列出讨论过的方案及各自优缺点、成本或风险"},{"key":"risks","title":"风险与依赖","instruction":"列出决策相关风险、外部依赖和缓解措施"},{"key":"dissent","title":"保留意见","instruction":"记录会上提出的反对意见或尚未消除的疑虑"}]',
  datetime('now', 'localtime')),
 ('interview', '客户访谈',
  '["summary","topics","people","open_issues","actions"]',
  '模板：客户访谈。优先保留客户原话与真实诉求，区分客户明确要求、潜在需求和我们自己的判断。不要替客户下结论；涉及承诺的内容必须标注是否需要内部确认。',
  1, '适合客户走访、需求调研、用户访谈。', '访谈',
  '[{"key":"needs","title":"客户诉求","instruction":"按优先级列出客户明确提出的需求与痛点"},{"key":"voice","title":"关键原话","instruction":"摘录最能代表客户态度的原话，保留语气"},{"key":"opportunity","title":"机会与风险","instruction":"提炼可能的机会、竞争信号和需要跟进的风险"}]',
  datetime('now', 'localtime')),
 ('training', '培训分享',
  '["summary","topics","people","actions"]',
  '模板：培训分享。提炼核心知识点、方法步骤和适用场景，保留关键例子与问答。不要把讲义逐字复述，优先输出能带走的结论和练习建议。',
  1, '适合内部培训、知识分享、讲座。', '培训',
  '[{"key":"takeaways","title":"核心知识点","instruction":"列出最重要的知识点及其适用场景"},{"key":"qa","title":"问答记录","instruction":"整理现场问题和回答要点，保留未解决的问题"}]',
  datetime('now', 'localtime'));
