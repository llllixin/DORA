"""Usage keeps provider measurements separate from admission estimates."""
from dataclasses import dataclass, field, asdict
from typing import Any, Generic, TypeVar

T = TypeVar('T')


class RuntimeFailure(RuntimeError):
    def __init__(self, category: str, *, temporary: bool = False, retry_after: float = 0):
        super().__init__(category)
        self.category, self.temporary, self.retry_after = category, temporary, retry_after


@dataclass(frozen=True)
class Usage:
    measurementStatus: str = 'unknown'
    inputTokens: int | None = None
    outputTokens: int | None = None
    totalTokens: int | None = None
    externalModelCalls: int = 0
    elapsedMs: int | None = None
    estimatedTokens: int | None = None
    estimator: str | None = None
    priceVersion: None = None
    costAmount: None = None
    currency: None = None
    usageDetails: tuple = ()
    diagnostics: tuple[str, ...] = ()

    def to_dict(self):
        out = asdict(self)
        out['usageDetails'] = {k: dict(v) for k, v in self.usageDetails}
        out['diagnostics'] = list(self.diagnostics)
        return out


@dataclass(frozen=True)
class ProviderEnvelope(Generic[T]):
    value: T
    usage: Usage = field(default_factory=Usage)
    requestedModel: str | None = None
    responseModel: str | None = None
    responseId: str | None = None
    adapterVersion: str = 'a04-v1'


def normalize_usage(raw: Any, protocol: str, *, external_calls: int = 1,
                    elapsed_ms: int | None = None, estimated_tokens: int | None = None) -> Usage:
    if not external_calls:
        return Usage(elapsedMs=elapsed_ms)
    raw = raw if isinstance(raw, dict) else {}
    keys = ('input_tokens', 'output_tokens', 'total_tokens') if protocol == 'responses' else (
        'prompt_tokens', 'completion_tokens', 'total_tokens')
    diagnostics = []
    def count(key):
        value = raw.get(key)
        if value is None: return None
        if type(value) is not int or value < 0:
            diagnostics.append('invalid_' + key); return None
        return value
    inp, out, total = [count(k) for k in keys]
    if protocol == 'embeddings': out = None
    if inp is not None and out is not None and total is not None and inp + out != total:
        diagnostics.append('inconsistent_total')
    details = []
    for key in ('input_tokens_details', 'output_tokens_details', 'prompt_tokens_details', 'completion_tokens_details'):
        if isinstance(raw.get(key), dict):
            values = tuple(sorted((k, v) for k, v in raw[key].items()
                                  if k in {'cached_tokens', 'cache_write_tokens', 'reasoning_tokens', 'audio_tokens',
                                           'accepted_prediction_tokens', 'rejected_prediction_tokens'}
                                  and type(v) is int and v >= 0))
            details.append((key, values))
    return Usage('measured' if total is not None else ('estimated' if estimated_tokens is not None else 'unknown'),
                 inp, out, total, external_calls, elapsed_ms, estimated_tokens,
                 'utf8-div3-v1' if estimated_tokens is not None else None,
                 usageDetails=tuple(details), diagnostics=tuple(diagnostics))


def aggregate_usage(usages: list[Usage], elapsed_ms: int) -> dict:
    external = [u for u in usages if u.externalModelCalls]
    complete = lambda key: sum(getattr(u, key) for u in external) if external and all(
        getattr(u, key) is not None for u in external) else None
    total = complete('totalTokens')
    estimates = [u.estimatedTokens for u in external if u.estimatedTokens is not None]
    out = Usage(measurementStatus='measured' if total is not None else ('estimated' if estimates else 'unknown'),
                inputTokens=complete('inputTokens'), outputTokens=complete('outputTokens'), totalTokens=total,
                externalModelCalls=sum(u.externalModelCalls for u in external), elapsedMs=elapsed_ms,
                estimatedTokens=sum(estimates) if estimates else None,
                estimator='utf8-div3-v1' if estimates else None).to_dict()
    out.update(knownTokenSubtotal=sum(u.totalTokens or 0 for u in external),
               unknownUsageAttempts=sum(u.totalTokens is None for u in external),
               knownInputTokenSubtotal=sum(u.inputTokens or 0 for u in external),
               knownOutputTokenSubtotal=sum(u.outputTokens or 0 for u in external))
    return out
