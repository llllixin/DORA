"""Thread-safe admission ledger. Reservations are never provider measurements."""
import json
import threading
import time
from dataclasses import dataclass, replace
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from uuid import uuid4
from app.runtime.contracts import RuntimeFailure, Usage


@dataclass(frozen=True)
class BudgetProfile:
    profileId: str
    route: str
    mode: str
    maxModelCalls: int
    maxProviderInvocations: int
    maxInputTokens: int
    maxOutputTokens: int
    maxTotalTokens: int
    maxOutputTokensPerCall: int
    maxElapsedMs: int
    attemptTimeoutMs: int
    maxRequestBytes: int
    maxContextChunks: int
    maxContextChars: int
    maxRetries: int
    retryBackoffMs: int
    maxConcurrency: int
    maxToolCalls: int
    maxSteps: int
    maxGraphHops: int = 0
    maxGraphNodes: int = 0
    estimator: str | None = None
    priceVersion: None = None
    costAmount: None = None
    currency: None = None

    def __post_init__(self):
        for key, value in vars(self).items():
            if key.startswith('max') or key.endswith('Ms'):
                if type(value) is not int or value < 0: raise ValueError('invalid budget field: ' + key)
        if not 0 < self.attemptTimeoutMs <= self.maxElapsedMs: raise ValueError('invalid budget timeout')
        if not self.maxProviderInvocations or not self.maxConcurrency or not self.maxRequestBytes: raise ValueError('unbounded profile')
        if self.maxModelCalls > self.maxProviderInvocations: raise ValueError('calls exceed invocations')
        if self.maxOutputTokensPerCall > self.maxOutputTokens: raise ValueError('output cap exceeds run limit')
        if self.maxTotalTokens > self.maxInputTokens + self.maxOutputTokens: raise ValueError('inconsistent token limits')
        if self.maxRetries not in (0, 1) or self.mode not in ('offline', 'external'): raise ValueError('invalid profile mode/retries')


def load_profile(route: str, external: bool) -> BudgetProfile:
    profiles = json.loads(Path(__file__).with_name('profiles.json').read_text())['profiles']
    mode = 'external' if external else 'offline'
    try: return BudgetProfile(**next(p for p in profiles if p['route'] == route and p['mode'] == mode))
    except StopIteration as exc: raise ValueError('unknown model route') from exc


@dataclass(frozen=True)
class Reservation:
    attemptId: str
    stage: str
    inputTokens: int
    outputTokens: int
    external: bool


class RunBudget:
    def __init__(self, profile: BudgetProfile, clock=None):
        self.profile, self.clock = profile, clock or time.monotonic
        self.started = self.clock(); self.deadline = self.started + profile.maxElapsedMs / 1000
        self.lock = threading.RLock(); self.pending = {}; self.settled = set()
        self._scopes = ContextVar('budget-scopes-'+uuid4().hex, default=())
        self.calls = self.invocations = self.tool_invocations = 0; self.consumed = [0, 0, 0]; self.overrun = False

    @contextmanager
    def limit_scope(self, profile):
        # A guard owns only request counters; every admission is also charged to
        # this parent ledger atomically. ContextVar keeps sibling requests apart.
        scope = RunBudget(profile, self.clock)
        scope.deadline = min(self.deadline, scope.deadline)
        marker = self._scopes.set((*self._scopes.get(), scope))
        try:
            self.check()
            yield scope
        finally:
            self._scopes.reset(marker)

    @property
    def effective_profile(self):
        values = vars(self.profile).copy()
        for scope in self._scopes.get():
            for key, value in vars(scope.profile).items():
                if key.startswith('max') or key == 'attemptTimeoutMs': values[key] = min(values[key], value)
                elif key == 'retryBackoffMs': values[key] = max(values[key], value)
        return replace(self.profile, **values)

    def remaining(self):
        return max(0., min([self.deadline, *(s.deadline for s in self._scopes.get())]) - self.clock())

    def check(self):
        if self.remaining() <= 0: raise RuntimeFailure('deadline_exceeded')

    def _check_reservation(self, stage, input_tokens, output_tokens, external):
        self.check(); p = self.profile
        if stage != 'tool' and sum(v['token'].stage != 'tool' for v in self.pending.values()) >= p.maxConcurrency:
            raise RuntimeFailure('budget_exceeded')
        if self.overrun or (stage != 'tool' and self.invocations >= p.maxProviderInvocations): raise RuntimeFailure('budget_exceeded')
        if stage == 'tool' and self.tool_invocations >= p.maxToolCalls: raise RuntimeFailure('budget_exceeded')
        if external:
            active = [v['token'] for v in self.pending.values() if v['token'].external]
            proposed = [input_tokens, output_tokens, input_tokens + output_tokens]
            reserved = [sum(t.inputTokens for t in active), sum(t.outputTokens for t in active),
                        sum(t.inputTokens + t.outputTokens for t in active)]
            caps = [p.maxInputTokens, p.maxOutputTokens, p.maxTotalTokens]
            if self.calls + sum(not v['dispatched'] for v in self.pending.values() if v['token'].external) >= p.maxModelCalls:
                raise RuntimeFailure('budget_exceeded')
            if any(self.consumed[i] + reserved[i] + proposed[i] > caps[i] for i in range(3)):
                raise RuntimeFailure('budget_exceeded')

    def reserve(self, stage, input_tokens, output_tokens, external):
        with self.lock:
            guards = (self, *self._scopes.get())
            for guard in guards: guard._check_reservation(stage, input_tokens, output_tokens, external)
            token = Reservation('a-' + uuid4().hex[:16], stage, input_tokens, output_tokens, external)
            for guard in guards:
                if stage == 'tool': guard.tool_invocations += 1
                else: guard.invocations += 1
                guard.pending[token.attemptId] = {'token': token, 'dispatched': False, 'guards': guards}
            return token

    def dispatch(self, token):
        with self.lock:
            guards = self.pending[token.attemptId]['guards']
            for guard in guards:
                guard.check(); state = guard.pending[token.attemptId]
                if guard.overrun: raise RuntimeFailure('budget_exceeded')
                if state['dispatched'] or not token.external: raise RuntimeFailure('invalid_dispatch')
                active = [v['token'] for v in guard.pending.values() if v['token'].external]
                reserved = [sum(t.inputTokens for t in active), sum(t.outputTokens for t in active),
                            sum(t.inputTokens + t.outputTokens for t in active)]
                caps = [guard.profile.maxInputTokens, guard.profile.maxOutputTokens, guard.profile.maxTotalTokens]
                if any(guard.consumed[i] + reserved[i] > caps[i] for i in range(3)): raise RuntimeFailure('budget_exceeded')
            for guard in guards:
                guard.pending[token.attemptId]['dispatched'] = True; guard.calls += 1

    def settle(self, token, usage: Usage):
        with self.lock:
            if token.attemptId in self.settled: return
            guards = self.pending[token.attemptId]['guards']
            for guard in guards:
                state = guard.pending.pop(token.attemptId); guard.settled.add(token.attemptId)
                if state['dispatched']:
                    values = [max(token.inputTokens, usage.inputTokens or 0), max(token.outputTokens, usage.outputTokens or 0),
                              max(token.inputTokens + token.outputTokens, usage.totalTokens or 0,
                                  (usage.inputTokens or 0) + (usage.outputTokens or 0))]
                    guard.consumed = [a + b for a, b in zip(guard.consumed, values)]
                    caps = [guard.profile.maxInputTokens, guard.profile.maxOutputTokens, guard.profile.maxTotalTokens]
                    guard.overrun = any(a > b for a, b in zip(guard.consumed, caps))

    def summary(self):
        with self.lock:
            elapsed = max(0, round((self.clock() - self.started) * 1000))
            return dict(profileId=self.profile.profileId, limits=vars(self.profile).copy(), externalModelCalls=self.calls,
                        providerInvocations=self.invocations, toolInvocations=self.tool_invocations, consumedInputAdmission=self.consumed[0],
                        consumedOutputAdmission=self.consumed[1], consumedTotalAdmission=self.consumed[2],
                        pendingAttempts=len(self.pending), elapsedMs=elapsed,
                        deadlineOverrunMs=max(0, elapsed - self.profile.maxElapsedMs), overrun=self.overrun)
