import type { CatalogPage, EvidenceSelection, JsonObject, QueryEvidence, QueryPacket, SourceDocument } from './queryTypes';
export class QueryClientError extends Error {
    constructor(public kind: 'network' | 'timeout' | 'cancelled' | 'http' | 'contract' | 'unavailable_mode', message: string, public httpStatus?: number, public reasonCode?: string, public runId?: string) { super(message); }
}
const invalid = (): never => { throw new QueryClientError('contract', '服务响应格式不完整，请重试或查看本次记录。'); };
export function object(v: unknown): JsonObject { if (!v || typeof v !== 'object' || Array.isArray(v))
    return invalid(); return v as JsonObject; }
function text(v: unknown): string { return typeof v === 'string' && v.length > 0 ? v : invalid(); }
function integer(v: unknown): number { return typeof v === 'number' && Number.isSafeInteger(v) && v >= 0 ? v : invalid(); }
function strings(v: unknown): string[] { return Array.isArray(v) && v.every(x => typeof x === 'string') ? v : invalid(); }
export function parseEvidence(v: unknown, expected?: EvidenceSelection): QueryEvidence {
    const e = object(v);
    text(e.evidenceId);
    text(e.contentHash);
    text(e.sourceKind);
    object(e.data);
    if (e.documentVersion !== undefined && e.documentVersion !== null && (!Number.isSafeInteger(e.documentVersion) || Number(e.documentVersion) < 1))
        return invalid();
    if (e.documentId !== undefined && e.documentId !== null)
        text(e.documentId);
    if (expected && (e.evidenceId !== expected.evidenceId || e.contentHash !== expected.contentHash))
        return invalid();
    return e as QueryEvidence;
}
export function parsePacket(v: unknown): QueryPacket {
    const p = object(v);
    if (p.contractVersion !== 'unified-query-v1-candidate' || typeof p.ok !== 'boolean')
        return invalid();
    text(p.runId);
    if (!['answered', 'partial', 'clarification_required', 'abstained', 'limited', 'failed'].includes(String(p.status)))
        return invalid();
    if (!Array.isArray(p.evidence) || !Array.isArray(p.citations) || !Array.isArray(p.sourceStates))
        return invalid();
    const evidence = p.evidence.map(e => parseEvidence(e));
    const ids = new Map(evidence.map(e => [e.evidenceId, e.contentHash]));
    if (ids.size !== evidence.length)
        return invalid();
    for (const c of p.citations) {
        const cite = object(c);
        if (ids.get(text(cite.evidenceId)) !== text(cite.contentHash))
            return invalid();
    }
    strings(p.missingParts);
    // Runtime-limited packets legitimately omit the clarification-only field.
    const clarifications = p.clarifications === undefined ? [] : strings(p.clarifications);
    p.sourceStates.forEach(object);
    if (p.answer !== undefined && typeof p.answer !== 'string')
        return invalid();
    return { ...p, clarifications } as QueryPacket;
}
export function parseCatalog(v: unknown): CatalogPage {
    const p = object(v);
    if (p.ok !== true || !Array.isArray(p.cards) || typeof p.hasMore !== 'boolean')
        return invalid();
    integer(p.total);
    integer(p.offset);
    integer(p.pageSize);
    text(p.catalogRevision);
    text(p.sourceRevision);
    text(p.indexStatus);
    for (const value of p.cards) {
        const c = object(value);
        for (const k of ['id', 'title', 'knowledgeType', 'sourceType', 'evidenceLevel', 'approvalStatus', 'currentEligibility'])
            text(c[k]);
        if (integer(c.version) < 1)
            return invalid();
    }
    if (p.cards.length > Number(p.pageSize) || Number(p.pageSize) > 25)
        return invalid();
    return p as CatalogPage;
}
export function parseDocument(v: unknown, id: string, version: number, kind: 'wiki' | 'stored'): SourceDocument {
    const p = object(v);
    const d = object(kind === 'wiki' ? p.card : p.document);
    const actualId = d.id;
    if (actualId !== id || d.version !== version || typeof d.content !== 'string')
        return invalid();
    text(d.title);
    return { ...d, id } as SourceDocument;
}
export function errorText(error: unknown): string {
    if (!(error instanceof QueryClientError))
        return '读取失败，请重试。';
    const labels = { network: '连接失败，请检查后端后重试。', timeout: '等待超时，请重试。', cancelled: '已停止等待，服务端可能仍在处理。', contract: error.message, unavailable_mode: '离线演示模式未提供此功能，请连接后端。', http: error.httpStatus === 409 ? '资料版本已改变，请重新读取。' : error.httpStatus === 404 ? '找不到这份资料或原始版本。' : error.httpStatus === 422 ? '请求范围有误，请调整后重试。' : '服务暂时不可用，请重试。' };
    return labels[error.kind];
}
