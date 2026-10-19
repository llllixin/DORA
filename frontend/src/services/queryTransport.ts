import { QueryClientError, object } from './queryContract';
export type TransportConfig = {
    base: string;
    mode: 'auto' | 'http' | 'mock';
    fetchImpl?: typeof fetch;
};
export function createQueryTransport({ base, mode, fetchImpl = fetch }: TransportConfig) {
    return { async request<T>(path: string, { method = 'GET', body, signal, timeoutMs = 10000, parse }: {
            method?: string;
            body?: unknown;
            signal?: AbortSignal;
            timeoutMs?: number;
            parse: (v: unknown) => T;
        }): Promise<T> {
            if (mode === 'mock')
                throw new QueryClientError('unavailable_mode', '此功能需要连接后端。');
            if (signal?.aborted)
                throw new QueryClientError('cancelled', '已停止等待');
            const controller = new AbortController();
            let timedOut = false;
            const cancel = () => controller.abort();
            signal?.addEventListener('abort', cancel, { once: true });
            const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
            try {
                const response = await fetchImpl(`${base.replace(/\/+$/, '')}${path}`, { method, body: body === undefined ? undefined : JSON.stringify(body), headers: body === undefined ? undefined : { 'Content-Type': 'application/json' }, signal: controller.signal });
                let value: unknown;
                try {
                    value = await response.json();
                }
                catch {
                    throw new QueryClientError(response.ok ? 'contract' : 'http', response.ok ? '服务未返回有效 JSON。' : `HTTP ${response.status}`, response.status);
                }
                if (!response.ok) {
                    const root = value && typeof value === 'object' && !Array.isArray(value) ? object(value) : {};
                    const detail = root.detail;
                    const d = detail && typeof detail === 'object' && !Array.isArray(detail) ? object(detail) : {};
                    throw new QueryClientError('http', typeof detail === 'string' ? detail : `HTTP ${response.status}`, response.status, typeof d.reasonCode === 'string' ? d.reasonCode : undefined, typeof d.runId === 'string' ? d.runId : undefined);
                }
                if (controller.signal.aborted)
                    throw new Error('aborted');
                return parse(value);
            }
            catch (error) {
                if (controller.signal.aborted)
                    throw new QueryClientError(timedOut ? 'timeout' : 'cancelled', '请求已结束');
                if (error instanceof QueryClientError)
                    throw error;
                throw new QueryClientError('network', '连接失败');
            }
            finally {
                clearTimeout(timer);
                signal?.removeEventListener('abort', cancel);
            }
        } };
}
