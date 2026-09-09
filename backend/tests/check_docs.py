# -*- coding: utf-8 -*-
"""docs 文档一致性自检（仅标准库，纯读文件，无 DB / 网络）。

用法：cd backend && python3 -m tests.check_docs
覆盖：
  1) 活文档（L0/L1）不得含未勾选待办 `- [ ]`（唯一允许 = docs/持续优化路线.md）；
  2) docs/开发过程记录.md 迭代编号从 1 起连续；
  3) docs/开发问题与经验.md 的 P/D 编号无重复；
  4) openspec/changes/archive/ 目录命名合规（yyyy-mm-dd-kebab）且非空；
  5) docs/持续优化路线.md 中 ✅ 行可回溯到归档目录或迭代号；
  6) 导航文档（AGENT.md / 版本路线图 / 文档地图 / openspec README）内反引号 .md 引用目标存在（死链）。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
CHANGES = ROOT / "openspec"
problems = []


def report(name: str, ok: bool, extra: str = "") -> None:
    if ok:
        print(f"  ✓ {name}")
    else:
        problems.append(f"{name} {extra}".rstrip())
        print(f"  ✗ {name} {extra}".rstrip())


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


print("[1] 活文档无未勾选待办（唯一允许 = 持续优化路线.md）")
todo_re = re.compile(r"- \[ \]")
no_todo = [
    ROOT / "AGENT.md",
    DOCS / "版本路线图.md",
    DOCS / "历史版本路线.md",
    DOCS / "优化方向.md",
    DOCS / "文档地图.md",
    DOCS / "开发过程记录.md",
    DOCS / "开发问题与经验.md",
    CHANGES / "README.md",
]
for v in (2, 3, 4, 5):
    no_todo.append(ROOT / f"RELEASE_NOTES_V{v}.md")
    if v >= 3:
        no_todo.append(DOCS / f"V{v}_ACCEPTANCE_CHECKLIST.md")
for f in no_todo:
    if not f.exists():
        report(f.name, False, "(文件缺失)")
        continue
    n = len(todo_re.findall(read(f)))
    report(f.name, n == 0, f"(found {n})" if n else "")

print("[2] dev-log 迭代编号连续")
dl = read(DOCS / "开发过程记录.md")
nums = [int(x) for x in re.findall(r"^## 迭代 (\d+)", dl, re.M)]
report("迭代 1..N 连续", bool(nums) and nums == list(range(1, len(nums) + 1)),
       f"(first={nums[0] if nums else '-'}, last={nums[-1] if nums else '-'}, count={len(nums)})")

print("[3] P/D 编号唯一")
pd = read(DOCS / "开发问题与经验.md")
ids = re.findall(r"^#{2,4}\s+(P|D)(\d{3})", pd, re.M)
seen = set()
dup = []
for kind, num in ids:
    key = kind + num
    if key in seen:
        dup.append(key)
    seen.add(key)
report("P/D 无重复", not dup, f"(dup={dup})" if dup else "")
report("同时含 P 与 D", any(k == "P" for k, _ in ids) and any(k == "D" for k, _ in ids))

print("[4] archive 目录命名合规")
arch = ROOT / "openspec" / "changes" / "archive"
dirs = sorted(p.name for p in arch.iterdir() if p.is_dir())
pat = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9-]+$")
bad = [d for d in dirs if not pat.match(d)]
report("命名 yyyy-mm-dd-kebab", not bad, f"(bad={bad})" if bad else "")
report("非空", len(dirs) > 0, f"(count={len(dirs)})")

print("[5] 持续优化路线 ✅ 行可回溯")
cont = read(DOCS / "持续优化路线.md")
trace = re.compile(r"2026-\d{2}-\d{2}-[a-z0-9-]+|迭代 \d+|docs 拆分|治理提交")
bad_rows = []
for line in cont.splitlines():
    if "✅" in line and line.lstrip().startswith(("-", "|")):
        if not trace.search(line):
            bad_rows.append(line.strip()[:90])
report("✅ 含归档目录或迭代号", not bad_rows, f"(bad={bad_rows})" if bad_rows else "")

print("[6] 导航文档死链（反引号 .md 引用）")
nav = [ROOT / "AGENT.md", DOCS / "版本路线图.md", DOCS / "文档地图.md", CHANGES / "README.md"]
ref_re = re.compile(r"`([^`]*\.md)`")
missing = []
for f in nav:
    if not f.exists():
        missing.append(f"{f.name} (文件缺失)")
        continue
    for ref in ref_re.findall(read(f)):
        if ref.startswith(("http", "../")) or "<" in ref or ".." in ref:
            continue
        rel = ref[2:] if ref.startswith("./") else ref
        candidates = {(ROOT / rel).resolve()}
        # 允许裸文件名（如 `历史版本路线.md`）默认落在 docs/ 下
        if not ref.startswith(("openspec/", "docs/", ".clinerules/", "RELEASE", "backend/")):
            candidates.add((DOCS / rel).resolve())
        if not any(c.exists() for c in candidates):
            missing.append(f"{f.name}: `{ref}`")
report("引用文件存在", not missing, f"(missing={missing})" if missing else "")

print()
if problems:
    print("check_docs: FAILED")
    for p in problems:
        print(" -", p)
    sys.exit(1)
print("check_docs: ALL GREEN")
