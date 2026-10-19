"""Bounded attempts with explicit contexts shared by orchestrators and workers."""
import json
import math
import os
import threading
import time
import urllib.request
import inspect
from dataclasses import asdict, is_dataclass
from dataclasses import replace
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from app.runtime.budget import RunBudget, load_profile
from app.runtime.contracts import ProviderEnvelope, RuntimeFailure, normalize_usage, aggregate_usage
from app.runtime import records
from app.db_budget import budget_scope,current_budget


def runtime_managed(method):
    """Declare a method that actually delegates attempts to managed_call."""
    method._dora_runtime_managed = True
    return method


def classify(exc):
    if isinstance(exc, RuntimeFailure): return exc
    if isinstance(exc, HTTPError):
        code = exc.code
        delay = 0.
        try:
            value = (exc.headers or {}).get('Retry-After', '0')
            try: delay = float(value)
            except ValueError: delay = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError): pass
        delay = delay if math.isfinite(delay) and delay >= 0 else 0
        return RuntimeFailure('rate_limited' if code == 429 else ('provider_server_error' if code >= 500 else
                              ('authentication_error' if code in (401, 403) else 'provider_request_error')),
                              temporary=code == 429 or code >= 500, retry_after=delay)
    if isinstance(exc, (TimeoutError, URLError)): return RuntimeFailure('provider_timeout' if isinstance(exc, TimeoutError) else 'transport_error', temporary=True)
    if isinstance(exc, json.JSONDecodeError): return RuntimeFailure('invalid_response')
    if isinstance(exc, ValueError):
        for category in ('citation_not_in_context', 'number_not_in_citations'):
            if str(exc).startswith(category): return RuntimeFailure(category)
        return RuntimeFailure('validation_error')
    return RuntimeFailure('provider_error')


class AttemptContext:
    def __init__(self, run, token):
        self.run, self.token = run, token
        self.timeout = min(run.effective_profile.attemptTimeoutMs / 1000, run.budget.remaining())
        self.dispatched = False; self.usage = normalize_usage(None, 'offline', external_calls=0)
        self.response_model = self.response_id = None
        self.adapter_version = 'a04-v1'
        self.dispatched_at = None

    def dispatch(self):
        # Persist preparation before the last admission check: a slow event sink
        # must not turn an expired reservation into a real network request.
        self.run.emit({'type': 'model_dispatch_preparing', 'attemptId': self.token.attemptId, 'stage': self.token.stage})
        self.run.budget.dispatch(self.token); self.dispatched = True
        self.timeout = min(self.timeout, self.run.budget.remaining())
        self.dispatched_at = datetime.now(timezone.utc).isoformat()

    def capture_usage(self, raw, protocol):
        self.usage = normalize_usage(raw.get('usage') if isinstance(raw, dict) else None, protocol,
                                    external_calls=1 if self.dispatched else 0,
                                    estimated_tokens=self.token.inputTokens + self.token.outputTokens if self.dispatched else None)
        if isinstance(raw, dict):
            self.response_model = raw.get('model') if isinstance(raw.get('model'), str) else None
            self.response_id = raw.get('id') if isinstance(raw.get('id'), str) else None

    def post_json(self, url, api_key, payload, protocol):
        if not api_key: raise RuntimeFailure('configuration_error')
        request = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'}, method='POST')
        self.dispatch()
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = bytearray()
            try:
                while True:
                    self.run.budget.check()
                    chunk = response.read(65536)
                    if not chunk: break
                    body.extend(chunk)
                    if len(body) > 4 * 1024 * 1024: raise RuntimeFailure('response_too_large')
            finally:
                # A complete response may arrive during a blocking read after the deadline.
                # Settle its usage even though the caller must reject its business value.
                try: self.capture_usage(json.loads(body.decode('utf-8')), protocol)
                except (ValueError, UnicodeError): pass
            raw = json.loads(body.decode('utf-8'))
        self.capture_usage(raw, protocol)
        return raw


class RunContext:
    def __init__(self, route, *, external=False, repository=None, run_id=None, input_data=None,
                 clock=None, sleep=None, profile=None, external_enabled=None):
        self.profile = profile or load_profile(route, external)
        self.budget = RunBudget(self.profile, clock)
        self.sleep = sleep or time.sleep; self.repository = repository
        self.external_enabled = (os.environ.get('DORA_MODEL_EXTERNAL_ENABLED', 'false').lower() == 'true'
                                 if external_enabled is None else external_enabled)
        self.events = []; self.usages = []; self.lock = threading.RLock(); self.finished = False
        self.active_operations = 0
        self.run_id = run_id
        if repository is not None and run_id is None:
            with budget_scope(self.budget):
                self.run_id = repository.create_agent_run(trigger='model_' + route[:20], input_data=input_data or {},
                                                         events=[], output={}, status='running')['id']
        self.emit({'type': 'model_run_started', 'profileId': self.profile.profileId})

    @property
    def effective_profile(self): return self.budget.effective_profile

    def limit_scope(self, profile): return self.budget.limit_scope(profile)

    def emit(self, event):
        with self.lock:
            self.events.append(event)
            with budget_scope(current_budget() or self.budget): records.append(self.repository, self.run_id, event)

    def execute(self, stage, provider, model, payload, external, perform, *, output_tokens=None):
        with self.lock:
            if self.finished: raise RuntimeFailure('run_finished')
            self.active_operations += 1
        try:
            return self._execute(stage, provider, model, payload, external, perform, output_tokens=output_tokens)
        finally:
            with self.lock: self.active_operations -= 1

    def _execute(self, stage, provider, model, payload, external, perform, *, output_tokens=None):
        if self.finished: raise RuntimeFailure('run_finished')
        if type(external) is not bool: raise RuntimeFailure('unknown_provider_capabilities')
        if external and not self.external_enabled: raise RuntimeFailure('external_disabled')
        profile = self.effective_profile
        size = len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8'))
        if size > profile.maxRequestBytes: raise RuntimeFailure('context_limit')
        for number in range(1, profile.maxRetries + 2):
            inp = math.ceil(size / 3) if external else 0
            out = (profile.maxOutputTokensPerCall if output_tokens is None else output_tokens) if external else 0
            if type(out) is not int or not 0 <= out <= profile.maxOutputTokensPerCall:
                raise RuntimeFailure('configuration_error')
            token = self.budget.reserve(stage, inp, out, external)
            attempt = AttemptContext(self, token); started = self.budget.clock(); error = None; value = None
            started_at = datetime.now(timezone.utc).isoformat()
            try:
                self.emit({'type': 'model_reserved', 'attemptId': token.attemptId, 'stage': stage,
                           'attemptNumber': number, 'reservation': {'inputTokens': inp, 'outputTokens': out}})
                value = perform(attempt)
                if isinstance(value, ProviderEnvelope):
                    attempt.usage = value.usage
                    attempt.response_model = value.responseModel or attempt.response_model
                    attempt.response_id = value.responseId or attempt.response_id
                    attempt.adapter_version = value.adapterVersion
                    model = value.requestedModel or model
                    value = value.value
                self.budget.check()
            except Exception as exc:
                error = classify(exc)
                if isinstance(exc, HTTPError): exc.close()
            finally:
                elapsed = max(0, round((self.budget.clock() - started) * 1000))
                if attempt.dispatched and not attempt.usage.externalModelCalls:
                    attempt.capture_usage({}, 'responses')
                usage = replace(attempt.usage, elapsedMs=elapsed)
                with self.lock:
                    self.budget.settle(token, usage)
                    self.usages.append(usage)
                    if attempt.dispatched:
                        # This audit write is deliberately after transport. Its
                        # timestamp is the admission time, not persistence time.
                        self.emit({'type': 'model_dispatch', 'attemptId': token.attemptId,
                                   'stage': stage, 'dispatchedAt': attempt.dispatched_at})
                    self.emit({'type': 'model_attempt', 'attemptId': token.attemptId, 'stage': stage,
                               'attemptNumber': number, 'provider': provider, 'requestedModel': model,
                               'responseModel': attempt.response_model, 'responseId': attempt.response_id,
                               'adapterVersion': attempt.adapter_version, 'status': 'failed' if error else 'done',
                               'startedAt': started_at, 'errorCategory': error.category if error else None, 'elapsedMs': elapsed,
                               'reservation': {'inputTokens': inp, 'outputTokens': out}, 'usage': usage.to_dict()})
            if error is None:
                self.budget.check()
                return value
            if not external or not error.temporary or number > profile.maxRetries: raise error
            delay = max(profile.retryBackoffMs / 1000, error.retry_after)
            if delay >= self.budget.remaining(): raise RuntimeFailure('deadline_exceeded')
            self.emit({'type': 'model_retry', 'stage': stage, 'afterAttemptId': token.attemptId, 'waitMs': round(delay * 1000)})
            self.sleep(delay)

    def diagnostics(self):
        with self.lock:
            budget = self.budget.summary()
            return {'runId': self.run_id, 'usage': aggregate_usage(self.usages, budget['elapsedMs']), 'budget': budget}

    def fallback(self, reason): self.emit({'type': 'model_fallback', 'fallbackReason': reason})

    def finish(self, output, status='done'):
        with self.lock:
            if self.active_operations or self.budget.summary()['pendingAttempts']: raise RuntimeFailure('attempts_in_flight')
            result = {**output, **self.diagnostics()}
            if not self.finished:
                # Terminal failure recording has a small independent cleanup
                # allowance; it never admits providers or business cache writes.
                from app.db_budget import RecordingBudget
                recording_budget = RecordingBudget() if status in ('failed','limited') else self.budget
                with budget_scope(recording_budget):
                    try: self.emit({'type': 'model_run_finished', 'status': status})
                    except Exception:
                        # Failure cleanup must still try the terminal row when
                        # only the append-event sink is transiently unavailable.
                        # Both writes share this same bounded cleanup allowance.
                        if status not in ('failed','limited'): raise
                    if self.repository is not None and self.repository.finish_agent_run(self.run_id, status, result) is None:
                        raise RuntimeError('runtime_run_missing')
                self.finished = True
            return result


def provider_run(route, external, run_context):
    return run_context or RunContext(route, external=external, repository=records.default_repository())


def managed_call(route, context, stage, provider, payload, perform, *, output_tokens=None):
    external = getattr(provider, 'external', None)
    if type(external) is not bool: raise RuntimeFailure('unknown_provider_capabilities')
    if external and (getattr(provider, 'supports_timeout', False) is not True or
                     (output_tokens != 0 and getattr(provider, 'supports_output_cap', False) is not True)):
        raise RuntimeFailure('unknown_provider_capabilities')
    run = provider_run(route, external, context)
    try:
        value = run.execute(stage, getattr(provider, 'kind', type(provider).__name__), payload.get('model', getattr(provider, 'model', None)),
                            payload, external, perform, output_tokens=output_tokens)
    except Exception as exc:
        if context is None: run.finish({'reason': classify(exc).category}, 'limited' if classify(exc).category in
                                      ('budget_exceeded', 'deadline_exceeded', 'external_disabled') else 'failed')
        raise
    if context is None: run.finish({'provider': getattr(provider, 'kind', None)})
    return value


def invoke_provider(provider, method_name, args, context, stage):
    method = getattr(provider, method_name)
    external = getattr(provider, 'external', None)
    if type(external) is not bool: raise RuntimeFailure('unknown_provider_capabilities')
    if getattr(method, '_dora_runtime_managed', False) is True:
        return method(*args, run_context=context)
    # Legacy local test adapters keep their public signatures. External adapters
    # must cooperate with transport/deadline/usage rather than hiding a network call.
    if external: raise RuntimeFailure('unknown_provider_capabilities')
    payload = {'arguments': [asdict(a) if is_dataclass(a) else a for a in args]}
    options = {'run_context':context} if 'run_context' in inspect.signature(method).parameters else {}
    return context.execute(stage, getattr(provider, 'kind', type(provider).__name__), getattr(provider, 'model', None),
                           payload, False, lambda attempt: method(*args, **options))
