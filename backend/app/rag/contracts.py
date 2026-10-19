"""知识源契约与固定问题集读取；不依赖额外 schema 库。"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE_ROOT = PROJECT_ROOT / "knowledge"
DOCUMENT_TYPES = {"glossary", "rule", "procedure", "case", "external"}
DOCUMENT_STATUSES = {"draft", "reviewed", "retired"}
SOURCE_TYPES = {"project", "official", "simulated", "verified_case"}
REQUIRED_FIELDS = {
    "id", "title", "knowledge_type", "status", "content", "source_type",
    "version", "valid_from", "reviewed_by", "updated_at",
}


class RagContractError(ValueError):
    pass


class RagIndexConflict(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class RagIndexUnavailable(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def load_documents(path: Path | None = None) -> list[dict[str, Any]]:
    source = path or KNOWLEDGE_ROOT / "documents.json"
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RagContractError(f"无法读取知识源: {exc}") from exc
    if not isinstance(raw, list):
        raise RagContractError("知识源顶层必须是数组")
    docs = [validate_document(item) for item in raw]
    keys = [(d["id"], d["version"]) for d in docs]
    if len(keys) != len(set(keys)):
        raise RagContractError("id + version 必须唯一")
    return docs


def validate_document(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise RagContractError("每篇知识必须是对象")
    missing = sorted(REQUIRED_FIELDS - set(item))
    if missing:
        raise RagContractError(f"知识缺少字段: {', '.join(missing)}")
    doc = dict(item)
    from app.wiki.contracts import is_legacy, validate_card
    if doc.get("schema_version") != 2 and not is_legacy(doc):
        raise RagContractError("new/changed documents cannot bypass Wiki governance")
    if not isinstance(doc["id"], str) or not doc["id"] or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in doc["id"]):
        raise RagContractError("id 只能包含小写字母、数字和连字符")
    if doc["knowledge_type"] not in DOCUMENT_TYPES:
        raise RagContractError(f"非法 knowledge_type: {doc['knowledge_type']}")
    if doc["status"] not in DOCUMENT_STATUSES:
        raise RagContractError(f"非法 status: {doc['status']}")
    if doc["source_type"] not in SOURCE_TYPES:
        raise RagContractError(f"非法 source_type: {doc['source_type']}")
    if not isinstance(doc["version"], int) or isinstance(doc["version"], bool) or doc["version"] < 1:
        raise RagContractError("version 必须是正整数")
    if len(str(doc["title"]).strip()) < 2 or len(str(doc["content"]).strip()) < 20:
        raise RagContractError("title 或 content 过短")
    if doc["source_type"] == "official" and not str(doc.get("source_url", "")).strip():
        raise RagContractError("official 文档必须有 source_url")
    if doc["source_type"] != "official" and not str(doc.get("source_ref", "")).strip():
        raise RagContractError("项目/案例文档必须有 source_ref")
    for field in ("metric_keys", "dimensions", "concept_ids", "aliases"):
        value = doc.setdefault(field, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise RagContractError(f"{field} 必须是字符串数组")
    _parse_date(doc["valid_from"], "valid_from")
    if doc.get("valid_to") is not None:
        _parse_date(doc["valid_to"], "valid_to")
    try:
        datetime.fromisoformat(str(doc["updated_at"]))
    except ValueError as exc:
        raise RagContractError("updated_at 必须是 ISO 时间") from exc
    if doc.get("schema_version") == 2:
        return validate_card(doc)
    if not isinstance(doc["reviewed_by"], str) or not doc["reviewed_by"].strip():
        raise RagContractError("reviewed_by 不能为空")
    return doc


def is_current_reviewed(doc: dict[str, Any], on_date: date | None = None) -> bool:
    today = on_date or date.today()
    if doc["status"] != "reviewed" or _parse_date(doc["valid_from"], "valid_from") > today:
        return False
    valid_to = doc.get("valid_to")
    return valid_to is None or _parse_date(valid_to, "valid_to") >= today


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RagContractError(f"{path.name}:{line_no} 不是合法 JSON") from exc
        if not isinstance(row, dict):
            raise RagContractError(f"{path.name}:{line_no} 必须是对象")
        rows.append(row)
    return rows


def load_eval_set(profile: str = "legacy-v1") -> list[dict[str, Any]]:
    questions = load_jsonl(KNOWLEDGE_ROOT / "eval/questions.jsonl")
    judgments = load_jsonl(KNOWLEDGE_ROOT / "eval/judgments.jsonl")
    by_id = {j.get("id"): j for j in judgments}
    if len(by_id) != len(judgments) or {q.get("id") for q in questions} != set(by_id):
        raise RagContractError("questions 与 judgments 的 id 必须唯一且一一对应")
    rows = [{**q, **by_id[q["id"]]} for q in questions]
    if profile == "legacy-v1":
        return rows
    if profile != "ontology-v2":
        raise RagContractError(f"未知评价 profile: {profile}")
    overlay = json.loads((KNOWLEDGE_ROOT / "eval/ontology-v2-judgments.json").read_text(encoding="utf-8"))
    changes = {row["id"]: row for row in overlay["overrides"]}
    if len(changes) != len(overlay["overrides"]) or not set(changes) <= set(by_id):
        raise RagContractError("评价版本含未知/重复题 ID")
    return [{**row, **changes.get(row["id"], {})} for row in rows]


def _parse_date(value: Any, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise RagContractError(f"{field} 必须是 YYYY-MM-DD") from exc
