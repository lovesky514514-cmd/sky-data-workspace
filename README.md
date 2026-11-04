# SKY Data Workspace 1.0

面向公开数据来源的本地桌面工作台。从选择网址和字段，到排队采集、查看原始证据、人工审核与导出，结果保存在本机。每条记录保留来源、时间、原始内容哈希和位置。

## 从哪里开始

- **安装使用**：从 [GitHub Releases](https://github.com/lovesky514514-cmd/sky-data-workspace/releases/latest) 下载 `SKY_Data_Workspace_1.0.0_x64_Setup.exe`，在 Windows x64 上运行安装器。安装包带有应用专用 WebView2 固定版。
- **第一次采集**：新建任务，输入公开网址，预览并选择字段，再开始采集。完成后在采集结果页检查来源并导出 Excel、CSV 或 JSON。
- **本地 AI**：运行 Ollama 并拉取 `qwen3.5:9b`，在设置中检查模型连接。助手可以检索随包知识卡和回答采集规则问题。AI 关闭时，采集、导出和本地知识检索仍可使用。
- **从源码构建**：依赖准备、离线安装包与验证命令见 [BUILDING.md](BUILDING.md)。

## 功能范围

| 功能 | 1.0 支持范围 |
| --- | --- |
| 数据采集 | 用户指定的静态 HTML、JSON、CSV、XML。支持任务队列、暂停、重试和定时运行。 |
| 证据与审核 | 保存原始响应，结果按来源、位置和 SHA-256 追溯。采集结果默认待审核。 |
| 导出与备份 | Excel 包含采集数据、来源信息与质量审核三张表。另有 CSV、JSON 和 SQLite 备份。 |
| 本地知识助手 | Ollama + Qwen3.5 9B。宿主验证结构、工具参数和引用 ID。业务事实依赖原始来源。 |
| 后续范围 | 全网搜索、动态网页渲染、PDF 和 OCR。 |

应用数据存放在 `%APPDATA%/io.sky.dataworkspace`。表格导出到 Windows 下载目录的 `SKY Data Workspace` 文件夹。迁移原始证据和任务时，备份整个应用数据目录。

## 项目结构

| 目录 | 职责 |
| --- | --- |
| `desktop/src/` | React 界面、任务页、轮询与桌面桥接。 |
| `desktop/src-tauri/` | Rust 桌面宿主、回环 API 代理、托盘和后台进程管理。 |
| `backend/` | Python 采集、解析、任务、证据、导出和 Ollama。 |
| `packaging/`、`scripts/` | 运行时冻结、离线打包和发布校验。 |
| `research/knowledge_cards.json` | 知识卡和引用来源，构建时生成只读检索索引。 |

## 许可与联系

第一方代码与文档采用 [MIT License](LICENSE)，维护者为 SuKoYa。图标分发范围见 [素材许可说明](ASSET_LICENSE.md)。依赖项和固定版 WebView2 保留各自的许可，安装包包含依赖声明。模型权重由 Ollama 单独管理。

报告问题时，请提供程序版本、Windows 版本、复现步骤和最小样例。提交日志前请移除回环令牌、用户路径或私有数据。
