-- 运行时设置、可定制纪要模板、结案状态与 ASR 指标

ALTER TABLE meeting ADD COLUMN closed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE meeting ADD COLUMN asr_seconds REAL;
ALTER TABLE meeting ADD COLUMN audio_seconds REAL;

CREATE TABLE IF NOT EXISTS app_setting (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS minute_template (
    key        TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    sections   TEXT NOT NULL,
    hint       TEXT NOT NULL DEFAULT '',
    builtin    INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

INSERT OR IGNORE INTO minute_template (key, name, sections, hint, builtin, updated_at)
VALUES
 ('standard', '常规会议',
  '["summary","topics","decisions","actions","open_issues"]',
  '模板：常规会议，均衡输出全部字段。', 1, datetime('now', 'localtime')),
 ('discussion', '座谈交流',
  '["summary","topics","people","decisions","actions"]',
  '模板：座谈交流，重点提炼各方观点与 people，弱化决策。', 1, datetime('now', 'localtime')),
 ('report', '工作汇报',
  '["summary","topics","open_issues","actions"]',
  '模板：工作汇报，重点提炼进展、问题与下一步，弱化决策。', 1, datetime('now', 'localtime'));

CREATE INDEX IF NOT EXISTS idx_meeting_closed ON meeting(closed);
