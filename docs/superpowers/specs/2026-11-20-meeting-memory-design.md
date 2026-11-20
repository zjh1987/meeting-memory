# 会议记忆系统 · 开发规格

版本：v1.0
日期：2026-11-20
状态：待评审
读者：实施开发人员
部署形态：单位内网私有化，单机部署
与现有原型的关系：**现有 FastAPI 原型仅作可行性验证，本规格定稿后按本文档重写工程结构**。

---

## 1. 产品定位与边界

### 1.1 一句话定位

会议结束即完成归档：音频自动转写、分人、生成结构化纪要，并沉淀为可追溯、可关联的会议记忆库。

### 1.2 核心价值

不是录音笔，也不是单次会议的纪要工具，而是**跨会议的记忆**：

- 每次会议的结论、待办、议题都以统一结构入库，可被后续会议比对。
- 关联只做"能拿原文举证"的两类：上次待办未落实、议题重复出现。每条关联必须携带原文引用，不做开放式联想。

### 1.3 用户与角色（P0）

| 角色 | 权限 |
|---|---|
| 使用人（唯一角色） | 口令登录；上传、查看全部会议、重试失败任务 |

P0 不建用户表，不做角色区分。多用户、部门权限属于 P2。

### 1.4 P0 明确不做

- 硬件录音笔、手机 App、小程序
- 实时转写（边开会边出字）
- 音频在线播放（P1 第一项）
- 多租户、多用户、部门权限
- 开放式 AI 洞察（决策矛盾、想法回收等属 P2）

---

## 2. 范围与验收

### 2.1 P0 范围

| 编号 | 能力 | 说明 |
|---|---|---|
| F1 | 网页上传 | 拖拽/选择音频，填标题，必选项目，选模板，显示上传进度 |
| F2 | 目录监听 | 外部设备把文件写入 `inbox/`，`.part` 改名完成后自动入库 |
| F3 | 自动流水线 | 转写（分人）→ 结构化纪要 → 关联 → 静态归档，全程状态可见 |
| F4 | 会议列表 | 按项目、状态、日期筛选；显示状态与待办数 |
| F5 | 会议详情 | 纪要分区展示、逐字稿、关联卡片、失败原因与重试按钮 |
| F6 | 纪要模板 | 常规会议 / 座谈交流 / 工作汇报，模板只控制展示与生成侧重 |
| F7 | 关联提示 | `pending_carryover`、`repeat_topic` 两类，带原文引用 |
| F8 | 失败处理 | 错误码可见、手动重试、自动重试 1 次、重启后恢复僵尸任务 |
| F9 | 静态归档 | 按日期归档为可直接打开的 HTML，含当日索引页 |
| F10 | 离线演示 | ASR/LLM 均为 mock 时能完整跑通全链路 |

### 2.2 P1（本期不做，规格预留）

1. 原文回听：点结论/待办播放对应 30 秒录音
2. 项目聚合页：项目下全部会议时间线
3. 待办推送飞书/企微、待办状态人工关闭
4. 纪要人工修订与修改留痕
5. 热词表管理界面
6. 会议类型/项目自动建议

### 2.3 P2

多用户与部门权限、洞察类分析、移动端与硬件接入、数据导出与开放 API。

### 2.4 P0 验收清单

全部通过才算交付：

1. 网页上传任意受支持格式后 3 秒内，列表出现"接收中/排队中"状态。
2. mock 模式下，上传到 `done` 全链路成功，详情页纪要、逐字稿、状态均正确。
3. 同一项目连续两场会议，第二场出现第一场"待办未落实"关联卡片，且卡片带原文引用。
4. `site/YYYY/MM/DD/{uid}/index.html` 与当日 `index.html` 均生成，可直接打开。
5. 处理进行中强制杀进程重启，任务能自动回到 `pending` 并最终完成。
6. 放在 `inbox/` 的 `.part` 文件在任何时刻都不会被转写；改名完成后才入库。

---

## 3. 术语

| 术语 | 含义 |
|---|---|
| uid | 会议唯一标识，格式 `YYYYMMDD-HHMMSS-xxxx`，同时用于文件名与静态路径 |
| 项目 | 会议归属的业务项目，是跨会议关联的唯一范围限定 |
| 完美文件 | 后缀在音频白名单内的文件；`.part` 一律视为未完成 |
| 阶段 | 会议处理中的一个步骤：接收、转写、纪要、关联 |
| 恢复点 | 重试时通过已有产物（transcript/minutes）判断从哪一步继续 |

---

## 4. 总体架构

### 4.1 形态

单机、单进程、多线程：

```
浏览器 ──HTTP──> FastAPI（单进程）
                    │
                    ├─ Harvester 线程：扫描 inbox → ready
                    ├─ Worker 线程：领取任务 → ASR → 纪要 → 关联 → 归档
                    ├─ Maintainer 线程：僵尸回收、.part 清理、磁盘水位检查
                    └─ SQLite（WAL）：会议/待办/关联/项目
                    │
                    └─ 文件目录：inbox / ready / archive / site
```

约束：

- uvicorn 必须以**单进程**启动（`workers=1`），多进程会导致重复领取任务。
- SQLite 开启 WAL、`busy_timeout=5000`，所有写事务保持短小。
- ASR 模型在进程内加载一次，常驻内存；Worker 串行处理，不做并行转写。

### 4.2 技术栈

| 层 | 选型 |
|---|---|
| Web | FastAPI + Uvicorn |
| 模板 | Jinja2 服务端渲染，原生 JS，无前端框架 |
| 存储 | SQLite 3（WAL），音频与归档走文件系统 |
| ASR | 本地 FunASR：`paraformer-zh` + `fsmn-vad` + `ct-punc` + `cam++` |
| 纪要 | OpenAI 兼容协议的内网 LLM（推荐 Qwen2.5-32B-Instruct 及以上，上下文 ≥32k） |
| 音频处理 | FFmpeg（外部命令），Python 侧只做调度与解析 |
| 部署 | systemd + Nginx（静态归档只读托管） |

### 4.3 数据流

```
网页上传 ─┐
          ├─> inbox/xxx.part ──rename──> inbox/xxx.m4a（+ 旁挂 .json）
设备落盘 ─┘                                      │
                                                 ▼
                                   Harvester：移入 ready/，建会议记录 pending
                                                 │
                                                 ▼
                          Worker：转写 transcribing → 纪要 minuting
                                                 │
                                                 ▼
                              关联 relating → 归档 → done
                                                 │
                                                 ▼
                    DB 更新 + site/YYYY/MM/DD/{uid}/index.html
```

---

## 5. 数据模型

### 5.1 表结构（DDL 即实现契约）

```sql
CREATE TABLE project (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE meeting (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    uid            TEXT NOT NULL UNIQUE,
    title          TEXT NOT NULL,
    project_id     INTEGER NOT NULL REFERENCES project(id),
    template_key   TEXT NOT NULL DEFAULT 'standard',
    recorded_at    TEXT NOT NULL,              -- 本地时间 'YYYY-MM-DD HH:MM:SS'
    duration_sec   INTEGER NOT NULL DEFAULT 0,
    audio_filename TEXT NOT NULL,              -- 相对 archive/ 或 ready/ 的文件名
    audio_size     INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'pending',
    error_code     TEXT,
    error_msg      TEXT,
    retry_count    INTEGER NOT NULL DEFAULT 0,
    next_retry_at  TEXT,
    transcript     TEXT,                       -- JSON 数组，见 5.4
    minutes        TEXT,                       -- JSON 对象，见 5.5
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    started_at     TEXT,
    finished_at    TEXT,
    heartbeat_at   TEXT
);

CREATE TABLE action_item (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id  INTEGER NOT NULL REFERENCES meeting(id),
    owner       TEXT,
    task        TEXT NOT NULL,
    due         TEXT,
    quote       TEXT NOT NULL,
    segment_ids TEXT NOT NULL,                 -- JSON 数组
    status      TEXT NOT NULL DEFAULT 'open',  -- open | done | cancelled
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE relation (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL REFERENCES meeting(id),
    target_id  INTEGER NOT NULL REFERENCES meeting(id),
    kind       TEXT NOT NULL,                  -- pending_carryover | repeat_topic
    detail     TEXT NOT NULL,
    quote      TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_meeting_project  ON meeting(project_id);
CREATE INDEX idx_meeting_status   ON meeting(status);
CREATE INDEX idx_meeting_recorded ON meeting(recorded_at);
CREATE INDEX idx_action_meeting   ON action_item(meeting_id);
CREATE INDEX idx_action_status    ON action_item(status);
CREATE INDEX idx_relation_meeting ON relation(meeting_id);
```

规则：

- 项目名唯一，上传时允许新建，重复则复用。种子数据固定包含 `未归类`，但**网页上传必须选择项目，不允许默认落到未归类**（目录监听设备未带项目时才落到未归类）。
- `audio_filename` 只存文件名，不存绝对路径；所在目录由文件状态决定（ready 或 archive），禁止在数据库中写入机器相关路径。
- `action_item.quote` 与 `segment_ids` 非空，这是"可举证"的硬约束。

### 5.2 时间与时区

- 服务器时区固定 `Asia/Shanghai`，所有时间字段存本地时间字符串，不做 UTC 转换。
- 目录扫描与重试判断统一用 `datetime.now()` 与同格式字符串比较。

### 5.3 纪要模板

```python
MINUTE_TEMPLATES = {
    "standard":   {"name": "常规会议", "sections": ["summary","topics","decisions","actions","open_issues"]},
    "discussion": {"name": "座谈交流", "sections": ["summary","topics","people","decisions","actions"]},
    "report":     {"name": "工作汇报", "sections": ["summary","topics","open_issues","actions"]},
}
```

模板只影响：生成 Prompt 的侧重说明、详情页展示哪些区块。**底层 JSON 字段永远完整**，否则跨会议无法比对。

### 5.4 转写 JSON

```json
[
  {"idx": 0, "start": 0.0, "end": 3.4, "speaker": "说话人1", "text": "今天主要过一下三季度进度。"},
  {"idx": 1, "start": 3.4, "end": 8.9, "speaker": "说话人2", "text": "系统这边功能都上完了，还有一个数据同步问题。"}
]
```

- `idx` 从 0 连续递增，是引用与回听的唯一依据。
- `speaker` 允许为 `说话人1..N`，P0 不做实名映射。

### 5.5 纪要 JSON（强制 schema）

```json
{
  "summary": "本次会议……",
  "topics": [
    {"title": "三季度进度", "points": ["功能已上线", "数据同步仍阻塞"], "segment_ids": [0, 1]}
  ],
  "decisions": [
    {"text": "月底前走一次高层协调", "quote": "这个不能再拖了，决定月底前走一次高层协调", "segment_ids": [5]}
  ],
  "actions": [
    {"owner": "张敏", "task": "整理数据同步问题清单", "due": "下周", "quote": "我下周先把问题清单整理出来", "segment_ids": [7]}
  ],
  "open_issues": [
    {"text": "座谈预算未定", "reason": "需看四季度是否调整", "segment_ids": [9]}
  ],
  "people": [
    {"name": "王总", "role": "主持人"}
  ]
}
```

校验规则（任一不满足即为不合法输出）：

1. `summary` 非空字符串；`topics` 至少 1 条。
2. `decisions`、`actions`、`open_issues` 中每条必须有非空 `quote` 与 `segment_ids`。
3. 所有 `segment_ids` 必须是转写中真实存在的 `idx`，越界即失败。
4. `actions` 每条 `task` 非空；`owner` 无法确定时写 `"待指定"`，不得空。
5. 只允许上述六个顶层字段，多余字段忽略。

---

## 6. 状态机与任务队列

### 6.1 状态定义

| 状态 | 含义 |
|---|---|
| `uploading` | 文件正在写入 inbox（仅网页上传会出现） |
| `pending` | 已入库，等待处理或等待重试时间到达 |
| `transcribing` | 转写中 |
| `minuting` | 生成纪要中 |
| `relating` | 计算关联、归档中 |
| `done` | 流程走完（允许纪要缺失，见 6.4） |
| `failed` | 无法继续，需人工处理 |

### 6.2 迁移表

| 当前 | 事件 | 目标 |
|---|---|---|
| uploading | Harvester 确认完整文件并移入 ready | pending |
| uploading | 超过 24 小时仍未进入 ready（文件缺失或损坏） | failed（`error_code=file_missing`） |
| pending | Worker 领取（到达 `next_retry_at`） | transcribing |
| transcribing | 转写成功 | minuting |
| transcribing | transcript 已存在（重试续跑） | minuting |
| transcribing | 转写失败且不可重试 / 重试耗尽 | failed |
| minuting | 纪要成功 | relating |
| minuting | 纪要失败 | done（保留逐字稿，`error_code` 标记） |
| relating | 关联与归档完成 | done |
| relating | 关联计算异常 | done（关联为空，`error_code=relation_failed`） |
| failed | 人工重试 | pending |
| transcribing / minuting / relating | 心跳超过 180 秒 | pending（`error_code=worker_timeout`，`retry_count+1`） |

### 6.3 领取任务（关键实现）

必须用事务保证只有一个 worker 能领到同一条：

```sql
BEGIN IMMEDIATE;
SELECT * FROM meeting
 WHERE status='pending'
   AND (next_retry_at IS NULL OR next_retry_at <= :now)
 ORDER BY id LIMIT 1;
-- 若有结果，立即：
UPDATE meeting
   SET status='transcribing',
       started_at=:now, heartbeat_at=:now, updated_at=:now,
       error_code=NULL, error_msg=NULL
 WHERE id=:id AND status='pending';
COMMIT;
```

- `UPDATE` 的影响行数必须为 1，否则回滚重领。
- 单 Worker 线程仍保留这套写法，便于后续扩到多线程。

### 6.4 恢复点

Worker 领到任务后先算恢复点，不盲目重跑：

```python
if transcript is None:     从 ASR 开始
elif minutes is None:      跳过 ASR，直接生成纪要
else:                      跳过 ASR 与纪要，只算关联与归档
```

因此"纪要失败但转写成功"的会议：`status=done`、`minutes` 为空、`error_code=llm_bad_json`，详情页显示"逐字稿已生成，纪要生成失败 [重新生成]"；重试走恢复点，只重跑纪要。

### 6.5 重试策略

- 自动重试：仅限瞬时错误 `asr_timeout`、`asr_unavailable`、`llm_unavailable`；状态回到 `pending`，`retry_count+1`，写入 `next_retry_at = now + 30s`；超过 `AUTO_RETRY_MAX` 则置 `failed`。
- 手动重试：接口触发，`retry_count+1`，不限次数，但每次记录日志。
- 不可重试：`upload_invalid`、`file_missing`、`storage_full`。前两者直接 `failed`；磁盘不足拒绝新上传而不是让在途任务失败。
- 重试入口：`POST /api/meetings/{uid}/retry`，`failed` 与"纪要缺失的 done"均可用。

### 6.6 心跳与僵尸回收

- Worker 处理期间启动心跳线程，每 60 秒更新 `heartbeat_at`。
- Maintainer 每 60 秒检查：处于三个处理态且 `heartbeat_at` 早于 180 秒前的记录，重置为 `pending`，`retry_count+1`，`error_code=worker_timeout`；同一会议被回收 3 次后置 `failed`，避免坏文件无限重试。
- 服务启动时执行一次同样的回收，覆盖"上次是被强杀"的场景。

### 6.7 幂等

- `uid` 唯一约束兜底。
- 重跑纪要时：先按恢复点确认，再 `DELETE action_item WHERE meeting_id=?` 后重插，`DELETE relation WHERE meeting_id=?` 后重插。
- 静态归档重复生成直接覆盖同名文件。

---

## 7. 采集端协议

### 7.1 网页上传

`POST /api/meetings`，`multipart/form-data`：

| 字段 | 必填 | 说明 |
|---|---|---|
| file | 是 | 音频文件，后缀白名单 `.m4a .mp3 .wav .opus .aac .amr .flac` |
| title | 否 | 缺省取文件名去后缀，服务端清洗非法字符 |
| project_name | 是 | 已存在则复用，不存在则新建 |
| template_key | 否 | 缺省 `standard` |

流程：

1. 校验后缀、大小（默认上限 500MB）、磁盘剩余空间（阈值 5GB）。
2. 生成 uid，写入 `inbox/{uid}__{safe_title}.{ext}.part`，边写边算 SHA-256 与大小。
3. `flush + os.fsync` 后关闭，写入旁挂 `{uid}__{safe_title}.json`（`{"project": "...", "title": "...", "recorded_at": "..."}`）。
4. `rename` 为完整后缀。
5. 插入 `meeting` 记录，`status=uploading`，返回 `{"uid": "..."}`。
6. Harvester 在下一个扫描周期确认文件完整、移动到 `ready/`，把状态置为 `pending`。

失败处理：任何一步失败删除 `.part`，返回对应错误码，不落库。

### 7.2 目录监听（设备/脚本接入）

设备必须遵守：

1. 先写 `inbox/{uid}__{title}.{ext}.part`。
2. 写完关闭后再写旁挂 JSON：`{"project": "...", "title": "...", "recorded_at": "...", "device_id": "..."}`。
3. 最后把 `.part` `rename` 为完整后缀。**先写元数据再改名**，保证服务端看到完整文件时元数据已就绪。

服务端：

- 只处理后缀在白名单内的文件，`.part` 一律跳过。
- `recorded_at` 优先取旁挂 JSON，缺失时取文件修改时间。
- 旁挂 JSON 解析失败不阻塞入库，项目落到 `未归类`，标题取文件名。
- 无对应 DB 记录时创建，`status=pending`；有记录（网页已建 `uploading`）时只做移动与状态推进。

### 7.3 清理

- Maintainer 删除 `inbox/` 中修改时间超过 24 小时的 `.part` 与孤立的旁挂 JSON。
- `ready/` 中超过 24 小时仍未被领取的文件告警（正常不应出现）。

### 7.4 去重

P0 以 `uid` 唯一约束防重；同一文件重复上传视为两次独立会议（P1 引入 `audio_sha256` 去重）。

---

## 8. 处理流水线

### 8.1 音频预处理

- 调用 FFmpeg 转 16kHz、单声道、PCM S16LE 的 wav，输出到 `ready/` 同名的临时文件，处理完删除。
- 时长通过 `ffprobe` 写入 `duration_sec`，失败则置 0 并继续（不阻塞流程）。

### 8.2 VAD 与长音频

- 目标单场支持 2 小时。
- 使用 FunASR 的 `fsmn-vad` 切分语音段，单段上限 30 秒、静音阈值按默认配置；超长连续语音强制在 30 秒处切分。
- 每段独立识别，时间戳按段偏移回填，最终按时间排序生成 `transcript`。
- 超过 2 小时的音频不拒绝，但记录告警日志；磁盘与内存压力由部署方评估。

### 8.3 转写与说话人分离

- 模型：`paraformer-zh`（ASR）+ `ct-punc`（标点）+ `cam++`（说话人向量）。
- 每个语音段提取说话人向量，按余弦相似度做层次聚类（阈值 0.75，可按现场调整），聚类结果映射为 `说话人1..N`。
- 热词：读取 `config/hotwords.txt`（一行一个词，人名、项目代号、单位名），传入 FunASR 热词参数。
- 输出必须包含 `start/end/speaker/text`，空文本段丢弃后重新编号 `idx`。
- 模型目录固定 `models/funasr/`，启动时校验存在，缺失则拒绝启动并给出明确提示。

### 8.4 纪要生成

Prompt 要求（写入 `pipeline/minutes.py` 的常量，便于评审）：

1. 只依据逐字稿，禁止补充未出现的事实。
2. 输出严格 JSON，字段与 5.5 完全一致，不得增删顶层字段。
3. `decisions`、`actions`、`open_issues` 每条必须给出原文 `quote` 与对应 `segment_ids`。
4. 模板侧重：
   - `standard`：均衡输出全部字段。
   - `discussion`：重点提取各方观点与 `people`，弱化决策。
   - `report`：重点提炼进展、问题、下一步，弱化决策。
5. 无法确定的信息写"待定"或"待指定"，不得编造。

长文本策略：

- 逐字稿字符数 ≤ 24000（约 32k token 内）时单次生成。
- 超过时分块（每块 8000 字，重叠 300 字），逐块生成"分块要点"，再以要点为输入做一次汇总，生成最终六个字段；`quote` 与 `segment_ids` 在分块阶段已绑定，汇总阶段只允许挑选、不允许新增引用。
- 调用参数：`temperature=0.1`，`response_format={"type": "json_object"}`（不支持该参数的模型则去掉并在 Prompt 中强调）。
- 超时 300 秒；失败自动重试 1 次，第二次仍失败按 6.4 降级。

### 8.5 关联规则

范围：同项目、已 `done`、`id < 当前会议`、最近 5 场。

规则一 `pending_carryover`（上次待办未落实）：

1. 取既往会议中 `status=open` 的待办。
2. 与本次会议全部待办做字符二元组 Jaccard 相似度，相似度 ≥ 0.5 视为本次已接续，不提示。
3. 每场既往会议最多生成一条关联：`detail="上次还有 N 条待办未见结论"`，N 为未接续条数，`quote` 取其中第一条待办的原文 `task`。
4. 只提示，不自动关闭任何待办。

规则二 `repeat_topic`（议题重复）：

1. 本次每个 `topics[].title` 与既往 `topics[].title` 比较。
2. 完全相同、互相包含或二元组相似度 ≥ 0.6，命中一次。
3. 同一目标会议最多提示一条，`detail="议题「X」上次也讨论过"`，`quote=本次议题标题`。

硬约束：`quote` 为空不得产生关联；关联计算异常不影响主流程（`done` + `error_code=relation_failed`）。

### 8.6 归档

- 详情页渲染为独立 HTML，内联 CSS，不依赖登录，路径 `site/YYYY/MM/DD/{uid}/index.html`。
- 当日索引 `site/YYYY/MM/DD/index.html`：列出当天全部 `done` 会议（标题、时间、项目、待办数、链接）。
- 根索引 `site/index.html`：按日期倒序列出有会议的日期。
- 归档为覆盖写入；会议重试成功或纪要重生成后重新导出。
- 静态目录由 Nginx 只读托管，P0 不做页面鉴权，**依赖内网访问控制**（见 14.2）。

---

## 9. 接口规格

### 9.1 鉴权

- 口令登录：`POST /login`，表单字段 `password`；成功后下发 `mm_session` Cookie（HttpOnly、SameSite=Lax、7 天）。
- Cookie 值为 `HMAC-SHA256(过期时间戳, COOKIE_SECRET)`，服务端校验签名与过期时间。
- 登录失败按 IP 限流：5 次/分钟，超出返回 429。
- 除 `/login`、`/healthz` 外，所有页面与接口均需登录；接口未登录返回 401 JSON。
- `POST /logout` 清除 Cookie。

### 9.2 页面路由

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/login` | 登录页 |
| POST | `/login` | 登录提交 |
| POST | `/logout` | 退出 |
| GET | `/` | 会议列表，支持 `project_id`、`status`、`date`、`page` 查询参数 |
| GET | `/m/{uid}` | 会议详情；处理中显示阶段，失败显示原因与重试按钮 |
| GET | `/healthz` | 健康检查，返回 `{"ok": true}`，不需登录 |

### 9.3 JSON 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/meetings` | 上传，见 7.1，返回 `{"uid": "..."}` |
| GET | `/api/meetings/{uid}/status` | 返回 `status`、`status_label`、`error_code`、`error_msg`、`retry_count`、`can_retry` |
| GET | `/api/meetings` | 列表，参数 `project_id`、`status`、`date`、`page`、`size`（默认 20），返回 `items` 与 `total` |
| POST | `/api/meetings/{uid}/retry` | 重试，返回新的 `status` |
| GET | `/api/projects` | 项目列表，用于上传表单 |

### 9.4 错误码

| HTTP | code | 场景 |
|---|---|---|
| 400 | `upload_invalid` | 后缀不支持、文件为空、标题清洗后为空 |
| 401 | `unauthorized` | 未登录 |
| 404 | `not_found` | uid 不存在 |
| 409 | `invalid_state` | 当前状态不允许重试 |
| 413 | `too_large` | 超过 500MB |
| 429 | `rate_limited` | 登录过于频繁 |
| 503 | `storage_full` | 磁盘低于 5GB，拒绝上传 |

响应格式统一：`{"error": {"code": "...", "message": "..."}}`。

---

## 10. 页面行为

### 10.1 列表页

- 每行：标题、项目、会议时间、时长、状态标签、待办数；点击进入详情或归档页。
- 筛选：项目下拉、状态下拉、日期（默认全部）。
- 处理中的行每 2 秒轮询一次状态接口，`done`/`failed` 后停止并局部刷新。
- 顶部入口：上传、静态归档（新窗口打开 `site/index.html`）。

### 10.2 详情页

- 状态区：阶段进度（接收 → 转写 → 纪要 → 关联）、失败原因、重试按钮。
- 纪要区：按模板 `sections` 渲染；每条决策/待办/待定事项显示原文引用。
- 关联区：卡片式，显示目标会议标题、时间、命中原因、引用；点击跳转目标会议。
- 逐字稿：按说话人分色，显示时间戳；P0 只读，不播放。
- 纪要缺失但逐字稿存在：显著提示"纪要生成失败"并提供重新生成按钮。

### 10.3 上传交互

- 选择文件后自动填充标题（文件名去后缀）、可选模板、必选项目（下拉 + 输入新建）。
- 显示上传百分比；上传成功后跳转详情页并开始轮询。
- 前端校验后缀与大小，服务端仍须完整校验。

---

## 11. 配置项

全部通过环境变量或 `.env` 注入，`config.py` 只负责读取与校验：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `APP_PASSWORD` | 无（必填） | 登录口令，未设置拒绝启动 |
| `COOKIE_SECRET` | 随机生成并持久化 | Cookie 签名密钥 |
| `DATA_DIR` | `./data` | inbox/ready/archive/db 的根目录 |
| `SITE_DIR` | `./site` | 静态归档输出 |
| `DB_PATH` | `{DATA_DIR}/app.db` | SQLite 路径 |
| `ASR_BACKEND` | `mock` | `mock` / `funasr` |
| `FUNASR_MODEL_DIR` | `./models/funasr` | 模型目录 |
| `FUNASR_DEVICE` | `cpu` | `cpu` / `cuda:0` |
| `HOTWORD_FILE` | `./config/hotwords.txt` | 热词表，可不存在 |
| `LLM_PROVIDER` | `mock` | `mock` / `openai` |
| `LLM_BASE_URL` | 无 | OpenAI 兼容接口地址 |
| `LLM_API_KEY` | 无 | 接口密钥（内网可留空） |
| `LLM_MODEL` | 无 | 模型名 |
| `MAX_UPLOAD_MB` | `500` | 上传上限 |
| `MIN_FREE_GB` | `5` | 磁盘水位 |
| `SCAN_INTERVAL` | `3` | inbox 扫描间隔（秒） |
| `HEARTBEAT_INTERVAL` | `60` | 心跳间隔（秒） |
| `ZOMBIE_TIMEOUT` | `180` | 心跳超时（秒） |
| `AUTO_RETRY_MAX` | `1` | 自动重试次数 |
| `RETRY_BACKOFF_SEC` | `30` | 自动重试退避 |
| `SPEAKER_THRESHOLD` | `0.75` | 说话人聚类阈值 |
| `LOG_DIR` | `./logs` | 日志目录 |

启动校验：`ASR_BACKEND=funasr` 时检查模型目录；`LLM_PROVIDER=openai` 时检查 `LLM_BASE_URL` 与 `LLM_MODEL`；不满足直接退出并打印缺失项。

---

## 12. 工程结构（重写目标）

```
app/
  main.py                 # FastAPI 装配、lifespan 启动线程、异常处理
  config.py               # 配置读取与校验
  api/
    auth.py               # 登录/登出/限流
    meetings.py           # 列表、详情、状态、重试
    upload.py             # 上传
    projects.py           # 项目列表
  core/
    models.py             # dataclass：Meeting/Segment/Minutes/ActionItem/Relation
    state.py              # 状态集合、合法迁移、恢复点计算
    similarity.py         # 字符二元组 Jaccard
  storage/
    db.py                 # 连接、PRAGMA、迁移执行
    migrations/001_init.sql
    meeting_repo.py       # 会议 CRUD、领取、状态更新
    action_repo.py
    relation_repo.py
    project_repo.py
    files.py              # 原子落盘、移动、归档路径、磁盘检查
  pipeline/
    harvester.py          # inbox → ready
    worker.py             # 领取、心跳、阶段推进、重试
    maintainer.py         # 僵尸回收、残片清理、水位检查
    media.py              # ffmpeg/ffprobe 封装
    transcribe.py         # 预处理、VAD、分段、说话人聚类
    minutes.py            # Prompt、JSON 校验、分块汇总
    relations.py          # 两类关联规则
    archive.py            # 静态导出
  providers/
    asr_base.py           # transcribe(segments) 接口
    asr_mock.py
    asr_funasr.py
    llm_base.py           # complete_json(prompt) 接口
    llm_mock.py
    llm_openai.py
  web/
    render.py             # Jinja 环境与渲染
    templates/
    static/
deploy/
  systemd/mm.service
  nginx/mm.conf
  backup.sh
config/hotwords.txt
models/funasr/
tests/
  unit/
  integration/
```

依赖方向：`api → pipeline/storage → core`，`pipeline → providers`；`providers` 不得反向依赖 `pipeline`；`web` 只读 `storage` 与 `core`，不直接触发处理。

---

## 13. 关键实现约束

1. **单写进程**：数据库写操作只在 API 与后台线程中发生，禁止多进程；部署脚本固定 `--workers 1`。
2. **原子性**：任何"写文件"都必须 `.part` + rename；任何状态推进都必须条件更新并检查影响行数。
3. **幂等**：重试不得产生重复待办、重复关联、重复归档目录。
4. **可举证**：纪要中没有原文引用的结论不进入决策与待办字段。
5. **失败可见**：任何异常都必须落到 `error_code`/`error_msg` 与日志，禁止静默吞掉。
6. **绝对路径不入库**：数据库只存文件名，目录由配置推导，便于整目录迁移。
7. **日志**：JSON Lines，字段至少 `ts`、`level`、`uid`、`event`、`detail`；按 10MB × 5 轮转。
8. **不引入额外中间件**：P0 不引入 Redis、Celery、消息队列。

---

## 14. 测试与验收

### 14.1 单元测试

| 模块 | 用例 |
|---|---|
| `core/state.py` | 合法迁移全部通过；非法迁移被拒绝；恢复点三种输入正确 |
| `storage/files.py` | `.part` 不进入待处理；rename 后可读；文件名清洗；磁盘阈值判断 |
| `pipeline/minutes.py` | schema 校验：缺 quote、越界 segment_ids、多字段、空 summary 均判失败 |
| `core/similarity.py` | 相同、包含、无关三组文本的相似度阈值命中 |
| `pipeline/relations.py` | 构造两场会议：有待办且未接续 → 出卡片；已接续 → 不出；议题重复 → 出卡片 |
| `api/upload.py` | 后缀白名单、大小限制、项目新建与复用 |

### 14.2 集成测试（mock provider）

1. 上传 1KB 音频 → 轮询至 `done` → 归档文件存在 → 每日索引包含该会议。
2. 直接向 `inbox/` 写 `.part` → 等待两个扫描周期 → 无会议记录；rename 后 → 出现记录并完成。
3. 处理中把 `heartbeat_at` 改为 10 分钟前 → Maintainer 回收 → 最终完成。
4. 模拟 LLM 返回非法 JSON → 会议 `done`、`minutes` 为空、`error_code=llm_bad_json`；调用重试 → 只重跑纪要（日志中不得出现 ASR 调用）。
5. 连续上传两场同项目会议 → 第二场关联数为 1 且 `quote` 非空。

### 14.3 手工验收

按 2.4 的六条逐条执行并记录结果。真实 ASR 另用一段 10 分钟、3 人对话的录音验证：说话人数正确、时间戳单调、纪要引用可对照原文。

---

## 15. 部署与运维

- systemd 单元：`WorkingDirectory` 指向应用目录，`EnvironmentFile=.env`，`ExecStart` 单 worker，`Restart=always`。
- Nginx：反向代理 `/` 到 127.0.0.1:8000；`/site/` 直接指向归档目录（只读，内网 IP 白名单）。
- 备份：每日 `sqlite3 app.db ".backup ..."` + `rsync` 音频归档与 site，保留 30 天。
- 监控：`/healthz`；日志中 `level=ERROR` 或 `event=worker_timeout` 出现即需人工查看。
- 迁移：数据库结构变更一律新增 `migrations/00X_*.sql`，启动时按序执行并记录版本表。P0 只需 001。

---

## 16. 里程碑

| 阶段 | 交付物 | 退出条件 |
|---|---|---|
| M0 骨架 | 工程结构、配置校验、DB 迁移、健康检查 | 服务可启动，`/healthz` 通过，空库可用 |
| M1 采集与队列 | 上传、目录监听、状态机、列表与轮询 | `.part` 不被处理；上传 3 秒内可见；重启恢复 |
| M2 转写 | mock ASR、FunASR 接入、说话人分离、逐字稿展示 | 10 分钟样例输出带说话人与时间戳的逐字稿 |
| M3 纪要 | 三种模板、schema 校验、降级与重生成、归档 | 三种模板均能生成合规 JSON；归档与索引生成 |
| M4 关联与重试 | 两类规则、自动/手动重试、僵尸回收 | 2.4 六条验收全部通过 |
| M5 交付 | systemd/Nginx/备份脚本、真实模型联调 | 真机部署演练一次，备份可恢复 |

M5 之外不排期 P1。

---

## 17. 风险与开放问题

| 风险 | 影响 | 应对 |
|---|---|---|
| 说话人分离在远场、多人座谈下不稳 | 纪要归属错人 | 阈值可配；P1 提供人工改名；P0 至少保证分段稳定 |
| CPU 转写 2 小时会议耗时过长 | 体验差 | 推荐 GPU；文档给出"目标 ≤ 60 分钟"作为参考指标，不作验收硬指标 |
| 静态归档无鉴权 | 内网越权查看 | Nginx 限定内网网段；P1 引入签名或登录；部署文档必须写明 |
| LLM 幻觉或编造引用 | 纪要不可信 | 低温度、强制 quote、segment_ids 校验、失败即降级 |
| 项目命名不一致 | 关联命中率下降 | 上传必选项目；P1 做项目合并与别名 |
| 磁盘增长 | 转写中断 | 水位拒绝上传；P1 增加留存期与自动清理 |

合规要求（P0 最低限度）：

1. 会议录音前由使用人负责告知参会人，产品在登录页与上传页展示使用须知。
2. 数据仅存于本单位内网服务器，不出网。
3. 登录保护 + 内网访问控制；静态归档目录同样受内网限制。
4. 删除能力：P0 提供运维级删除脚本（按 uid 删除音频、归档与数据库记录），P1 做界面化删除与留存期策略。

开放问题（不阻塞开发）：

- LLM 具体型号由部署方按算力选定，只需满足 OpenAI 兼容协议与 ≥32k 上下文，代码不感知型号。
- 热词表初始内容由业务方提供，开发阶段用示例词占位。
