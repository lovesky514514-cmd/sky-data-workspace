from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files
import ssl

root = Path(SPECPATH).parent
datas = [(str(root / "artifacts/bundle/knowledge.sqlite3"), "knowledge")]
datas += collect_data_files("certifi") + collect_data_files("jsonschema_specifications")
certificate_policy = Path(ssl.__file__).parent / "codex-rejected-cas.pem"
if certificate_policy.is_file():
    datas.append((str(certificate_policy), "."))
a = Analysis([str(root / "scripts/runtime_entry.py")],
    pathex=[str(root / "backend")], binaries=[], datas=datas,
    hiddenimports=[], hookspath=[], runtime_hooks=[],
    excludes=["tkinter", "pytest", "PIL", "numpy", "matplotlib", "pip", "setuptools"],
    noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="sky-data-runtime",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=True, icon=str(root / "desktop/src-tauri/icons/icon.ico"))
