"""Agent 可调用的只读工具。

注册表同时持有公开 schema、参数校验和执行函数，避免把模型给出的名称直接映射到任意 Python 方法。
"""
from dataclasses import dataclass
from typing import Any, Callable

from app.repository import Repository


class ToolInputError(ValueError):
    """模型给出的工具参数不符合契约。"""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    validate: Callable[[dict[str, Any]], dict[str, Any]]
    execute: Callable[[Repository, dict[str, Any]], dict[str, Any]]

    def public_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ToolInputError("arguments 必须是对象")
    return value


def _text(args: dict[str, Any], name: str, *, required: bool, max_length: int) -> str:
    value = args.get(name, "")
    if not isinstance(value, str):
        raise ToolInputError(f"{name} 必须是字符串")
    value = value.strip()
    if required and not value:
        raise ToolInputError(f"{name} 不能为空")
    if len(value) > max_length:
        raise ToolInputError(f"{name} 最长 {max_length} 个字符")
    return value


def _integer(args: dict[str, Any], name: str, default: int, minimum: int, maximum: int) -> int:
    value = args.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolInputError(f"{name} 必须是整数")
    if not minimum <= value <= maximum:
        raise ToolInputError(f"{name} 必须在 {minimum}..{maximum} 之间")
    return value


def _reject_extra(args: dict[str, Any], allowed: set[str]) -> None:
    extra = sorted(set(args) - allowed)
    if extra:
        raise ToolInputError(f"不支持的参数：{', '.join(extra)}")


def _validate_metric(raw: dict[str, Any]) -> dict[str, Any]:
    args = _object(raw)
    _reject_extra(args, {"metric_key", "dimension", "limit"})
    return {
        "metric_key": _text(args, "metric_key", required=True, max_length=64),
        "dimension": _text(args, "dimension", required=False, max_length=100),
        "limit": _integer(args, "limit", 50, 1, 200),
    }


def _query_metric(repo: Repository, args: dict[str, Any], *, run_context=None, tool_reserved=False) -> dict[str, Any]:
    from app.query.service import default_service
    result=default_service(repo).metric(args['metric_key'],args['dimension'] or None,args['limit'],
                                       run_context=run_context,tool_reserved=tool_reserved)
    return {**result,'metric_key':args['metric_key']}


_KNOWLEDGE_TYPES = {"problem", "opportunity", "change", "lesson"}


def _validate_search(raw: dict[str, Any]) -> dict[str, Any]:
    args = _object(raw)
    _reject_extra(args, {"query", "types", "top_k", "sourceKinds", "knowledgeTypes", "includeSimulated"})
    raw_types = args.get("types", [])
    if not isinstance(raw_types, list) or not all(isinstance(item, str) for item in raw_types):
        raise ToolInputError("types 必须是字符串数组")
    types = list(dict.fromkeys(item.strip() for item in raw_types if item.strip()))
    unknown = sorted(set(types) - _KNOWLEDGE_TYPES)
    if unknown:
        raise ToolInputError(f"不支持的知识类型：{', '.join(unknown)}")
    from app.query.contracts import QuerySearchRequest
    from pydantic import ValidationError
    try:
        QuerySearchRequest(query=_text(args,'query',required=True,max_length=300),**{k:args[k] for k in ('sourceKinds','knowledgeTypes','includeSimulated') if k in args})
    except ValidationError as exc: raise ToolInputError('invalid source selection') from exc
    return {
        **{k:args[k] for k in ('sourceKinds','knowledgeTypes','includeSimulated') if k in args},
        "query": _text(args, "query", required=True, max_length=300),
        "types": types,
        "top_k": _integer(args, "top_k", 5, 1, 10),
    }


def _search_knowledge(repo: Repository, args: dict[str, Any], *, run_context=None, tool_reserved=False) -> dict[str, Any]:
    from app.query.service import default_service
    from app.query.contracts import QuerySearchRequest
    request=QuerySearchRequest(query=args['query'],topK=args['top_k'],archiveTypes=args['types'],
                               **{k:args[k] for k in ('sourceKinds','knowledgeTypes','includeSimulated') if k in args})
    return default_service(repo).search(request,run_context=run_context,tool_reserved=tool_reserved,
                                         response_projection=_legacy_search_projection)


def _legacy_search_projection(result):
    references=[]
    for e in result['evidence']:
        references.append({'entry_type':'wiki' if e['sourceKind']=='wiki' else e['archiveType'],
                           'source_id':e['documentId'] if e['sourceKind']=='wiki' else e['sourceId'],
                           'code':e.get('archiveCode','') if e['sourceKind']=='archive' else '',
                           'title':e['data']['title'],'evidenceId':e['evidenceId']})
    hits=[{**e,**ref} for e,ref in zip(result['evidence'],references)]
    return {**result,'hits':hits,'references':references}


def execute_tool(spec,repo,args,*,run_context):
    from inspect import signature,Parameter
    parameters=signature(spec.execute).parameters
    options={name:value for name,value in [('run_context',run_context),('tool_reserved',True)]
             if name in parameters and parameters[name].kind in (Parameter.KEYWORD_ONLY,Parameter.POSITIONAL_OR_KEYWORD)}
    return spec.execute(repo,args,**options)


def readonly_tools() -> dict[str, ToolSpec]:
    """每次返回新字典，测试可安全替换执行函数而不污染全局状态。"""
    return {
        "query_metric": ToolSpec(
            name="query_metric",
            description="按指标和可选维度读取已持久化的时间序列；未知指标返回空结果。",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "required": ["metric_key"],
                "properties": {
                    "metric_key": {"type": "string", "maxLength": 64},
                    "dimension": {"type": "string", "maxLength": 100},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                },
            },
            validate=_validate_metric,
            execute=_query_metric,
        ),
        "search_knowledge": ToolSpec(
            name="search_knowledge",
            description="检索允许的Wiki和归档，返回来源等级与可回看引用；模拟来源默认排除。",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "maxLength": 300},
                    "types": {"type": "array", "items": {"type": "string", "enum": sorted(_KNOWLEDGE_TYPES)}, "uniqueItems": True},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 10},
                    "sourceKinds": {"type":"array","minItems":1,"items":{"type":"string","enum":["wiki","archive"]}},
                    "knowledgeTypes": {"type":"array","items":{"type":"string","enum":["glossary","rule","procedure","case","external"]}},
                    "includeSimulated": {"type":"boolean","default":False},
                },
            },
            validate=_validate_search,
            execute=_search_knowledge,
        ),
    }
