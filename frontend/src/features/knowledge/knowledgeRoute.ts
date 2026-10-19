export type ArchiveType = '' | 'problem' | 'opportunity' | 'change' | 'lesson';
export type KnowledgeRoute = {
    task: 'ask' | 'wiki' | 'archive';
    archiveType: ArchiveType;
    openKey: string;
};
export function readKnowledgeRoute(hash: string): KnowledgeRoute {
    const p = new URLSearchParams(hash.replace(/^#/, '')), task = p.get('task'), type = p.get('archiveType') || '';
    return { task: task === 'wiki' || task === 'archive' ? task : 'ask', archiveType: ['problem', 'opportunity', 'change', 'lesson'].includes(type) ? type as ArchiveType : '', openKey: (p.get('open') || '').slice(0, 300) };
}
export function knowledgeHref(route: KnowledgeRoute) { const p = new URLSearchParams({ page: 'knowledge', task: route.task }); if (route.archiveType)
    p.set('archiveType', route.archiveType); if (route.openKey)
    p.set('open', route.openKey); return `#${p}`; }
export function writeKnowledgeRoute(route: KnowledgeRoute) { location.hash = knowledgeHref(route); }
