-- 内置模板的场景信息与更专业的默认提示词

UPDATE minute_template
SET scene='常规',
    description='均衡输出摘要、议题、决定、待办与待定，适合大多数例会。',
    hint='模板：常规例会。先给出 3-6 句管理层摘要，再按议题归纳讨论要点；决定事项写清结论与影响范围，待办写明负责人和截止时间，待定事项说明卡点与下一步。'
WHERE key='standard' AND hint='模板：常规会议，均衡输出全部字段。';

UPDATE minute_template
SET scene='座谈',
    description='适合座谈、交流、研讨，重点保留各方观点与共识。',
    hint='模板：座谈交流。重点保留各方观点、分歧与共识，标注发言人；涉及诉求和承诺时保留原话；决策不明确时放入待定事项，不要替参会人下结论。',
    custom_sections='[{"key":"views","title":"各方观点","instruction":"按发言人归纳立场、分歧与共识"}]'
WHERE key='discussion' AND hint='模板：座谈交流，重点提炼各方观点与 people，弱化决策。';

UPDATE minute_template
SET scene='汇报',
    description='适合工作汇报，突出进展、风险与下一步计划。',
    hint='模板：工作汇报。按“进展与数据—问题与风险—下一步计划”组织；保留关键数字和里程碑；没有明确结论的内容不要写成决定。',
    custom_sections='[{"key":"metrics","title":"关键数据","instruction":"列出带数字的进展、指标和里程碑"}]'
WHERE key='report' AND hint='模板：工作汇报，重点提炼进展、问题与下一步，弱化决策。';

UPDATE minute_template SET scene='常规',
  description='均衡输出摘要、议题、决定、待办与待定，适合大多数例会。'
WHERE key='standard' AND (description='' OR description IS NULL);
UPDATE minute_template SET scene='座谈',
  description='适合座谈、交流、研讨，重点保留各方观点与共识。'
WHERE key='discussion' AND (description='' OR description IS NULL);
UPDATE minute_template SET scene='汇报',
  description='适合工作汇报，突出进展、风险与下一步计划。'
WHERE key='report' AND (description='' OR description IS NULL);

