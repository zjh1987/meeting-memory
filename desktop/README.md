# 会议记忆 Windows 录音端

轻量级 Windows 桌面录音客户端：登录后一键开始、暂停、结束录音，结束后自动上传到会议记忆服务器并跟踪纪要生成状态。只包含登录与录音界面，不展示纪要和后台管理功能。

## 功能

- 浅色卡片式界面，登录、项目、设备、录音和待上传列表在一屏内完成
- 16 kHz 单声道 WAV 录音，兼容外接拾音器 / USB 麦克风
- 录音设备下拉选择，记住上次使用的设备
- 开始、暂停、继续、结束并上传
- 上传进度、服务器转写/纪要生成状态提示
- 上传失败自动保留本地文件，支持一键重试和 30 秒自动重试
- 最小化后显示半透明圆形悬浮窗，可直接暂停或结束录音；双击时长恢复主窗口
- 关闭窗口或最小化到系统托盘，录音不中断
- 进程异常退出后自动修复 WAV 头并恢复待上传录音
- 可选“记住登录状态（7 天）”，密码不落盘；支持主动退出账号
- 支持内网自签 HTTPS 证书

## 使用

1. 运行 `MeetingMemoryRecorder-v1.1.0.exe`。
2. 填写服务器地址（例如 `http://192.168.110.14:8000`）、账号和密码。
3. 登录后选择项目、纪要模板和录音设备，点击“开始录音”。
4. 结束后点击“结束并上传”，程序会自动上传并显示处理状态。
5. 上传成功后本地 WAV 自动删除；失败的文件保留在“待上传录音”列表。

录音时间、项目、模板和服务器地址会保存在本机；只有勾选“记住登录状态”时才会保存 7 天会话 Cookie，密码从不保存。

## 数据与文件位置

- 配置：`%APPDATA%\MeetingMemoryRecorder\config.json`
- 登录会话：`%APPDATA%\MeetingMemoryRecorder\session.json`（仅在勾选记住登录时存在）
- 录音与待上传文件：`%APPDATA%\MeetingMemoryRecorder\recordings\`
- 运行日志：`%APPDATA%\MeetingMemoryRecorder\logs\recorder.log`

## 构建

需要 Python 3.10+（含 Tkinter）和 Windows：

```powershell
cd desktop
.\build.ps1
```

输出：`desktop\dist\MeetingMemoryRecorder-v1.1.0.exe`。

首次运行时 Windows SmartScreen 可能提示未知发布者，选择“更多信息 → 仍要运行”即可；正式分发建议使用代码签名证书。

## 说明

- 客户端使用与网页、手机 App 相同的 `/login`、`/api/projects`、`/api/templates`、`/api/meetings` 接口。
- 会议归属、成员数据隔离和自动命名由服务器负责，桌面端上传后自动归属当前登录账号。
- 如果服务器使用自签 HTTPS，请勾选“信任自签 HTTPS 证书”。
