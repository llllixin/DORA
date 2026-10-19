import type { KnowledgeEntry, KnowledgeStats } from '../types';
import type { CatalogParams, EvidenceSelection, QueryRequest, SearchRequest } from './queryTypes';
import { object, parseCatalog, parseDocument, parseEvidence, parsePacket, QueryClientError } from './queryContract';
import { createQueryTransport } from './queryTransport';
import type { TransportConfig } from './queryTransport';
export function createKnowledgeApi(config: TransportConfig) {
    const { request } = createQueryTransport(config);
    const id = encodeURIComponent;
    return {
        answerQuestion: (body: QueryRequest, signal?: AbortSignal) => request('/query/answer', { method: 'POST', body, signal, timeoutMs: 35000, parse: parsePacket }),
        searchKnowledge: (body: SearchRequest, signal?: AbortSignal) => request('/query/search', { method: 'POST', body, signal, timeoutMs: 20000, parse: parsePacket }),
        getRunEvidence: (selection: EvidenceSelection, signal?: AbortSignal) => request(`/query/runs/${id(selection.runId)}/evidence/${id(selection.evidenceId)}`, { signal, parse: v => parseEvidence(v, selection) }),
        getWikiCatalog: (params: CatalogParams, signal?: AbortSignal) => { const q = new URLSearchParams(); Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== '')
            q.set(k, String(v)); }); return request(`/wiki/catalog?${q}`, { signal, parse: parseCatalog }); },
        getWikiCard: (documentId: string, version: number, signal?: AbortSignal) => request(`/wiki/cards/${id(documentId)}?version=${version}`, { signal, parse: v => parseDocument(v, documentId, version, 'wiki') }),
        getStoredDocument: (documentId: string, version: number, signal?: AbortSignal) => request(`/rag/documents/${id(documentId)}?version=${version}`, { signal, parse: v => parseDocument(v, documentId, version, 'stored') }),
        getKnowledgeArchive: (type: string, signal?: AbortSignal) => request(`/knowledge${type ? `?type=${id(type)}` : ''}`, { signal, parse: v => {
                const p = object(v);
                const stats = object(p.stats);
                if (!Array.isArray(p.entries) || !['problem', 'opportunity', 'change', 'lesson'].every(k => Number.isSafeInteger(stats[k]) && Number(stats[k]) >= 0))
                    throw new QueryClientError('contract', '归档响应格式不完整。');
                for (const value of p.entries) {
                    const e = object(value);
                    if (!Number.isSafeInteger(e.id) || !['problem', 'opportunity', 'change', 'lesson'].includes(String(e.entry_type)) || !['source_id', 'code', 'title', 'content', 'note', 'created_at'].every(k => typeof e[k] === 'string'))
                        throw new QueryClientError('contract', '归档条目格式不完整。');
                }
                return p as {
                    entries: KnowledgeEntry[];
                    stats: KnowledgeStats;
                };
            } }),
    };
}
const env = import.meta.env ?? {};
export const knowledgeApi = createKnowledgeApi({ base: env.VITE_API_BASE_URL || '/api', mode: env.VITE_API_MODE === 'mock' ? 'mock' : env.VITE_API_MODE === 'http' ? 'http' : 'auto' });
