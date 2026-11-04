"""Collect installed build-input notices; no fetched research source is shipped."""
import importlib.metadata as metadata
import json
from pathlib import Path
from release_version import release_version
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'desktop/src-tauri/resources/licenses'
OUTPUT.mkdir(parents=True, exist_ok=True)
entries = []


def collect(name, version, license_name, origin, files):
    destination = OUTPUT / origin / (name + '-' + version)
    destination.mkdir(parents=True, exist_ok=True)
    copied = []
    for source in sorted(set(files)):
        if source.is_file():
            target = destination / source.name
            if target.exists() and target.read_bytes() != source.read_bytes():
                target = destination / (source.parent.name + '-' + source.name)
            shutil.copyfile(source, target)
            copied.append(str(target.relative_to(OUTPUT)).replace('\\', '/'))
    entries.append({'name':name, 'version':version, 'license':license_name,
                    'ecosystem':origin, 'notices':copied})


for distribution in metadata.distributions():
    name = distribution.metadata.get('Name', 'unknown')
    if name.lower() == 'sky-data-workspace':
        continue
    files = []
    for file in distribution.files or []:
        if file.name.upper().startswith(('LICENSE', 'LICENCE', 'NOTICE', 'COPYING', 'AUTHORS')):
            files.append(Path(distribution.locate_file(file)))
    collect(name, distribution.version,
            distribution.metadata.get('License-Expression') or distribution.metadata.get('License', 'See notices'),
            'python-build-environment', files)

python_root = Path(sys.base_prefix)
collect('CPython', '.'.join(map(str,sys.version_info[:3])), 'PSF-2.0', 'python',
        list(python_root.glob('LICENSE*')) + list((python_root/'Lib').glob('LICENSE*')))

lock = json.loads((ROOT/'desktop/package-lock.json').read_text(encoding='utf-8'))
for package, value in lock['packages'].items():
    if not package or value.get('dev'):
        continue
    folder = ROOT/'desktop'/package
    files = [p for p in folder.iterdir() if p.is_file() and p.name.upper().startswith(('LICENSE','LICENCE','NOTICE','COPYING'))]
    name = value.get('name') or package.split('node_modules/')[-1]
    collect(name.replace('/','__'), value['version'], value.get('license','See notices'), 'javascript', files)

result = subprocess.run(['cargo','metadata','--manifest-path',str(ROOT/'desktop/src-tauri/Cargo.toml'),
                         '--format-version','1','--locked','--offline','--filter-platform','x86_64-pc-windows-msvc'],
                        check=True, capture_output=True, text=True,encoding='utf-8')
for package in json.loads(result.stdout)['packages']:
    if package['name'] == 'sky-data-workspace':
        continue
    folder = Path(package['manifest_path']).parent
    files = [p for p in folder.iterdir() if p.is_file() and p.name.upper().startswith(('LICENSE','LICENCE','NOTICE','COPYING'))]
    for candidate in ['LICENSES','licenses']:
        if (folder/candidate).is_dir():
            files += list((folder/candidate).rglob('*'))
    collect(package['name'],package['version'],package.get('license') or 'See notices','rust-build-graph',files)

(OUTPUT/'dependencies.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf-8')
(OUTPUT/'THIRD_PARTY_NOTICES.txt').write_text(
    f'SKY Data Workspace {release_version()} — third-party notices\n\n'
    'First-party application code belongs to its owner. Third-party components retain their own notices.\n'
    'This directory records production JavaScript dependencies, the locked Windows Rust build graph,\n'
    'and the Python build environment (a conservative superset of modules frozen into the runtime).\n'
    'See dependencies.json and the adjacent license files for exact package versions and terms.\n'
    'PyInstaller redistributes its bootloader under GPL with its stated exception; see its bundled notices.\n'
    'Ollama and Qwen weights are managed separately. The fixed WebView2 runtime is redistributed with its own notices.\n'
    'The application embeds eight original research-rule cards with source links, not cloned repository source.\n'
    'The supplied artwork is used as the application icon at the owner\'s request.\n',encoding='utf-8')
print(json.dumps({'packages_recorded':len(entries),'notice_files':sum(len(e['notices']) for e in entries)}))
