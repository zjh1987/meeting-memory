-- 纪要模板排序：常用模板可以调整到下拉列表前面，第一项作为默认模板

ALTER TABLE minute_template ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 100;

UPDATE minute_template
SET sort_order = CASE key
    WHEN 'standard' THEN 10
    WHEN 'weekly' THEN 20
    WHEN 'report' THEN 30
    WHEN 'project_review' THEN 40
    WHEN 'decision_review' THEN 50
    WHEN 'interview' THEN 60
    WHEN 'discussion' THEN 70
    WHEN 'training' THEN 80
    ELSE 100
END;
