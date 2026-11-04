# Windows 构建与验证

使用 Windows x64、Python 3.12、Node.js 24、Rust MSVC 工具链和 Visual Studio C++ 构建工具。在项目根目录运行以下命令。

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements.lock
.venv/Scripts/python.exe -m pip install --no-deps --no-build-isolation -e backend
npm.cmd ci --prefix desktop
cargo fetch --locked --manifest-path desktop/src-tauri/Cargo.toml
```

## WebView2 固定版

下载 [微软官方 x64 CAB](https://msedge.sf.dl.delivery.mp.microsoft.com/filestreamingservice/files/b7919cc9-680d-4253-bf32-732988e68aa6/Microsoft.WebView2.FixedVersionRuntime.156.0.4314.58.x64.cab)，核对 SHA-256 为 `857dcfd6f7035508a29645fa2978c3a6a841f220df77cc366d318894e19f4792`，然后解包。

```powershell
expand.exe .\Microsoft.WebView2.FixedVersionRuntime.156.0.4314.58.x64.cab -F:* desktop/src-tauri
```

固定运行时目录由 `desktop/src-tauri/tauri.conf.json` 指定。安装包将它与应用一起交付，升级 WebView2 时需要重新构建发行包。参见 [Tauri 固定版配置](https://v2.tauri.app/distribute/windows-installer/#fixed-version)。

## 安装包与发布

```powershell
./scripts/build_desktop.ps1
```

构建先检查 Tauri、Python、npm 和 Cargo 版本一致性，再执行后端测试、前端格式检查和前端单元测试。随后从版本库中的知识卡生成 SQLite 索引，收集许可声明，冻结 Python 并构建当前用户模式的 NSIS 安装包。安装器输出到 `release/`。

发布时更新各生态的版本字段及锁文件。运行 `scripts/release_version.py` 可以单独检查版本。发布清单根据本次安装器、二进制哈希和测试报告生成，不复用历史版本的报告。

构建工具、生成的运行时、安装包、历史研究快照和本地数据库属于派生或本机文件。提交到 GitHub 时将安装器与 SHA-256 作为 Release 附件上传。公开发布前需要确认用户提供图标的分发权限。

## 无窗口验证

```powershell
.venv/Scripts/python.exe scripts/probe_native.py
.venv/Scripts/python.exe scripts/probe_desktop_ui.py
```

安装包生成后执行以上命令。第一个命令验证桌面 EXE 能启动并回收随包后台。第二个命令启动隔离后台和本机预览，检查真实网页采集、导出、备份和界面操作。首次运行无窗口浏览器测试前，在 `desktop/` 中执行 `npx playwright install chromium`，或给脚本传入 `--browser <已安装的 headless_shell.exe 路径>`。报告保存在 `artifacts/acceptance/<版本>/`。

`scripts/probe_installed_iana.py` 使用正在运行的本地后台采集 IANA HTML 表格，并将导出的工作簿与官方 CSV 核对。生成全部报告后，运行 `scripts/release_manifest.py --native-report <native.json> --ui-report <ui/report.json> --iana-report <iana.json>` 输出安装包清单和 SHA-256。

真实模型测试需要本机 Ollama 运行并已安装 `qwen3.5:9b`。运行 `scripts/live_qwen_acceptance.py` 可以检查文本、图像、工具调用和字段映射。
