-- 会议归属账号与自动命名标记：普通成员只看到自己的会议

ALTER TABLE meeting ADD COLUMN owner_id INTEGER REFERENCES app_user(id);
ALTER TABLE meeting ADD COLUMN title_auto INTEGER NOT NULL DEFAULT 0;

-- 历史会议归属到最早的管理员，保证升级后管理员仍能看到全部数据。
UPDATE meeting
SET owner_id = (SELECT id FROM app_user WHERE role='admin' ORDER BY id LIMIT 1)
WHERE owner_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_meeting_owner ON meeting(owner_id);
