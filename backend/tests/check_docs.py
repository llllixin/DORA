"""纯文件检查：文档入口、P/D 与迭代编号、OpenSpec 索引及历史原文完整性。
运行：cd backend && python -m tests.check_docs；不访问数据库或网络。
"""
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / 'docs'
problems = []
learning_archives = [DOCS / 'archive/2026-09-20/历史/README.md']


def read(path):
    return path.read_text(encoding='utf-8')


def report(name, ok, details=''):
    print(f"  {'✓' if ok else '✗'} {name}" + (f' — {details}' if details else ''))
    if not ok:
        problems.append(name)


def anchors(text):
    result = set(re.findall(r'<a\s+id="([^"]+)"', text))
    duplicates = {}
    for heading in re.findall(r'^#{1,6}\s+(.+)$', text, re.M):
        slug = re.sub(r'[^\w\- ]', '', heading.lower()).replace(' ', '-')
        count = duplicates.get(slug, 0)
        duplicates[slug] = count + 1
        result.add(slug if count == 0 else f'{slug}-{count}')
    return result


print('[1] 当前入口与待办边界')
required = [ROOT / p for p in ('README.md', 'AGENT.md', 'docs/fullstack/README.md',
    'docs/agent/README.md', 'docs/agent/问题与经验.md', 'docs/持续优化路线.md', 'docs/开发问题与经验.md',
    'docs/开发过程记录.md', 'docs/面试项目技术说明.md', 'docs/archive/README.md')]
required += learning_archives
missing = [str(p.relative_to(ROOT)) for p in required if not p.is_file()]
report('入口存在', not missing, str(missing) if missing else '')
live = [p for p in DOCS.rglob('*.md') if 'archive' not in p.relative_to(DOCS).parts]
live += [ROOT / p for p in ('README.md', 'AGENT.md', 'backend/README.md',
    '.clinerules/project-conventions.md', 'openspec/README.md')]
live += learning_archives
wrong = [str(p.relative_to(ROOT)) for p in live if p.is_file() and p.name != '持续优化路线.md'
         and re.search(r'^- \[ \]', read(p), re.M)]
report('当前说明的未完成任务只在路线', not wrong, str(wrong) if wrong else '')

print('[2] 迭代与问题编号')
log = DOCS / '开发过程记录.md'
nums = [int(x) for x in re.findall(r'^## 迭代 (\d+)', read(log), re.M)] if log.exists() else []
report('迭代 1..N 连续', bool(nums) and nums == list(range(1, len(nums) + 1)))
pd = DOCS / '开发问题与经验.md'
ids = re.findall(r'^#{2,4}\s+([PD]\d{3})', read(pd), re.M) if pd.exists() else []
report('P/D 无重复且两类均存在', len(ids) == len(set(ids)) and
       any(x.startswith('P') for x in ids) and any(x.startswith('D') for x in ids))

print('[3] 冻结原文与迁移清单')
try:
    manifest = json.loads(read(DOCS / 'archive/manifest.json'))
except (OSError, ValueError) as exc:
    manifest = []
    report('迁移清单可读取', False, str(exc))
errors, originals, bundles = [], set(), {}
for item in manifest:
    old, new = item['original'], item['archived']
    path = ROOT / new
    if old in originals:
        errors.append(f'重复原路径 {old}')
    originals.add(old)
    try:
        if item.get('bundle'):
            bundle, member = item['bundle'], item['member']
            members = bundles.setdefault(bundle, set())
            if member in members:
                errors.append(f'重复压缩包成员 {bundle}: {member}')
            members.add(member)
            with zipfile.ZipFile(ROOT / bundle) as archive:
                content = archive.read(member)
            if path.exists():
                errors.append(f'已打包的独立入口再次出现 {new}')
        else:
            content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != item['sha256']:
            errors.append(f'原文内容改变 {new}')
    except (OSError, KeyError, zipfile.BadZipFile, RuntimeError) as exc:
        errors.append(f'原文无法读取 {new}: {exc}')
    if item['mode'] == 'moved' and (ROOT / old).exists():
        errors.append(f'迁移前入口再次出现 {old}')
    if item['mode'] == 'snapshot' and not (ROOT / old).is_file():
        errors.append(f'当前版本缺失 {old}')
for bundle, members in bundles.items():
    try:
        with zipfile.ZipFile(ROOT / bundle) as archive:
            names = archive.namelist()
            if set(names) != members or len(names) != len(members):
                errors.append(f'压缩包成员与清单不一致 {bundle}')
    except (OSError, zipfile.BadZipFile) as exc:
        errors.append(f'压缩包无法读取 {bundle}: {exc}')
report('原文完整且无重复入口', bool(manifest) and not errors, '; '.join(errors))

print('[4] OpenSpec 索引')
dirs = {p.name for p in (ROOT / 'openspec/changes/archive').iterdir() if p.is_dir()}
report('归档命名且非空', bool(dirs) and all(re.fullmatch(r'\d{4}-\d{2}-\d{2}-[a-z0-9-]+', n) for n in dirs))
index = read(ROOT / 'openspec/README.md')
linked = re.findall(r'\]\(changes/archive/([^/]+)/tasks\.md\)', index)
report('每个归档恰有一个索引', set(linked) == dirs and len(linked) == len(dirs))
caps = {p.parent.name for p in (ROOT / 'openspec/specs').glob('*/spec.md')}
linked_caps = re.findall(r'\]\(specs/([^/]+)/spec\.md\)', index)
report('每个能力恰有一个入口', set(linked_caps) == caps and len(linked_caps) == len(caps))
opened = {p.name for p in (ROOT / 'openspec/changes').iterdir() if p.is_dir() and p.name != 'archive'}
linked_open = re.findall(r'\]\(changes/([^/]+)/proposal\.md\)', index)
report('未归档变更索引准确', set(linked_open) == opened and len(linked_open) == len(opened))

print('[5] 当前 Markdown 链接与锚点')
errors, count = [], 0
for path in [*live, DOCS / 'archive/README.md', *(ROOT / 'openspec/specs').glob('*/spec.md')]:
    if not path.is_file():
        continue
    for raw in re.findall(r'\[[^\]\n]*\]\(([^)\n]+)\)', read(path)):
        parsed = urlsplit(raw.strip().strip('<>'))
        if parsed.scheme or parsed.netloc:
            continue
        count += 1
        target = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
        if not target.exists() and path.name in {'开发过程记录.md', '开发问题与经验.md'}:
            for item in manifest:
                if target == (ROOT / item['original']).resolve():
                    target = ROOT / item.get('bundle', item['archived'])
                    break
        if not target.exists():
            errors.append(f'{path.relative_to(ROOT)}: {raw}')
        elif parsed.fragment and target.suffix == '.md' and ('archive' not in target.parts or target in learning_archives):
            if unquote(parsed.fragment) not in anchors(read(target)):
                errors.append(f'{path.relative_to(ROOT)}: 锚点 {raw}')
report('本地链接与当前锚点有效', not errors, '; '.join(errors) if errors else f'{count} links')

print('[6] 导航不再指向旧路径')
nav = [ROOT / p for p in ('README.md', 'AGENT.md', 'docs/fullstack/README.md',
    'docs/agent/README.md', 'openspec/config.yaml', '.clinerules/project-conventions.md')]
errors = []
for path in nav:
    if not path.exists():
        continue
    for item in manifest:
        if item['mode'] == 'moved' and item['original'] in read(path):
            errors.append(f"{path.relative_to(ROOT)}: {item['original']}")
report('使用新导航', not errors, '; '.join(errors))
print('[7] 路线中的完成记录可回溯')
trace = re.compile(r'2026-\d{2}-\d{2}-[a-z0-9-]+|迭代 \d+|docs 拆分|治理提交')
roadmap = DOCS / '持续优化路线.md'
errors = [line[:100] for line in read(roadmap).splitlines()
          if '✅' in line and line.lstrip().startswith(('-', '|')) and not trace.search(line)]
report('完成项有归档或迭代依据', not errors, '; '.join(errors))

print('\ncheck_docs:', 'FAILED' if problems else 'ALL GREEN')
sys.exit(1 if problems else 0)
