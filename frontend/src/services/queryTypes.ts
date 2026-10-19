export type JsonObject = Record<string, unknown>;
export type QueryStatus = 'answered' | 'partial' | 'clarification_required' | 'abstained' | 'limited' | 'failed';
export type QueryOptions = {
    topK?: number;
    sourceKinds?: ('wiki' | 'archive')[];
    knowledgeTypes?: string[];
    archiveTypes?: string[];
    includeSimulated?: boolean;
};
export type QueryRequest = QueryOptions & {
    question: string;
    expectedDataRevision?: string;
    expectedSourceRevision?: string;
};
export type SearchRequest = QueryOptions & {
    query: string;
};
export type EvidenceSelection = {
    kind: 'evidence';
    runId: string;
    evidenceId: string;
    contentHash: string;
};
export type SourceSelection = EvidenceSelection | {
    kind: 'wiki' | 'stored';
    documentId: string;
    version: number;
};
export type QueryEvidence = JsonObject & {
    evidenceId: string;
    contentHash: string;
    sourceKind: string;
    data: JsonObject;
    readAt?: string | null;
    documentId?: string | null;
    documentVersion?: number | null;
};
export type QueryPacket = JsonObject & {
    contractVersion: string;
    runId: string;
    ok: boolean;
    status: QueryStatus;
    answer?: string;
    question?: string;
    query?: string;
    evidence: QueryEvidence[];
    citations: {
        evidenceId: string;
        contentHash: string;
    }[];
    missingParts: string[];
    clarifications: string[];
    sourceStates: JsonObject[];
};
export type CatalogCard = {
    id: string;
    title: string;
    version: number;
    knowledgeType: string;
    sourceType: string;
    evidenceLevel: string;
    approvalStatus: string;
    currentEligibility: string;
};
export type CatalogPage = {
    ok: boolean;
    cards: CatalogCard[];
    total: number;
    offset: number;
    pageSize: number;
    hasMore: boolean;
    sourceRevision: string;
    catalogRevision: string;
    indexStatus: string;
};
export type CatalogParams = {
    q?: string;
    knowledgeType?: string;
    offset?: number;
    pageSize?: number;
    includeSimulated?: boolean;
    expectedCatalogRevision?: string;
};
export type SourceDocument = JsonObject & {
    id: string;
    title: string;
    version: number;
    content: string;
};
