# 贡献指南

感谢你愿意改进会议记忆。提交代码前请先看一遍下面的约定。

## 环境

- Python 3.10
- FFmpeg（真实转写时需要，单元测试不需要）
- 测试依赖：`pip install -r requirements-dev.txt`

## 开发流程

1. Fork 仓库并从 `main` 拉出分支，分支名建议 `feat/xxx`、`fix/xxx`。
2. 先写或补充测试，再改实现。
3. 本地跑通全部测试：

   ```bash
   python -m pytest -q
   ```

4. 提交信息使用 Conventional Commits 风格，例如 `feat: 支持按项目筛选会议`、`fix: 修复重试后状态未更新`。
5. 发起 Pull Request，说明改动目的、行为变化与测试结果。

## 代码约定

- 保持单进程 + SQLite 的部署形态，不引入需要常驻外部服务的强依赖。
- 新的 ASR / LLM 能力请实现 `app/providers/` 下的接口，并保留 mock 实现，确保离线可测。
- 数据库结构变更放在 `app/storage/migrations/`，按编号追加，不修改已发布的迁移。
- 前端模板保持无构建步骤，直接由 Jinja2 渲染，避免引入 Node 工具链。
- 不提交 `.env`、`data/`、`site/`、`logs/`、`models/` 等运行时内容。

## 报告问题

- 功能缺陷与使用问题请开 Issue，附上操作系统、部署方式（Docker / systemd / 离线包）、日志片段与复现步骤。
- 安全漏洞请勿开公开 Issue，按 [SECURITY.md](SECURITY.md) 私下报告。
