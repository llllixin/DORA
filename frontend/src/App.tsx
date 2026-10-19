import { useEffect, useState, useRef } from "react";
import type { DataSource, InsightType, Page } from "./types";
import { insights } from "./data";
import { Sidebar } from "./components/layout/Sidebar";
import { Topbar } from "./components/layout/Topbar";
import { EvidenceDrawer } from "./components/dora/EvidenceDrawer";
import { CapabilityPanel } from "./components/dora/CapabilityPanel";
import { DataSourceModal } from "./components/dora/DataSourceModal";
import { OnboardingPage } from "./features/onboarding/OnboardingPage";
import { PulsePage } from "./features/pulse/PulsePage";
import { InsightPage } from "./features/insight/InsightPage";
import { ActionPage } from "./features/action/ActionPage";
import { KnowledgePage } from "./features/knowledge/KnowledgePage";
import { WatchPage } from "./features/watch/WatchPage";
import { dataConnection, createAction, getEvidence, refreshReasoningApi, syncRemoteData } from './services/doraApi';
import type { Evidence } from "./types";

const readHash = (): { page: Page; type: InsightType; idx: number } => {
  const s = location.hash.replace(/^#/, "");
  const p = new URLSearchParams(s);
  const page = (p.get("page") as Page) || "pulse";
  return {
    page,
    type: (p.get("type") as InsightType) || "problem",
    idx: Math.max(0, Number(p.get("idx") || 0) || 0),
  };
};
const writeHash = (page: Page, type: InsightType, idx: number) => {
  const p = new URLSearchParams({ page });
  if (page === "insight") {
    p.set("type", type);
    p.set("idx", String(idx));
  }
  history.replaceState(null, "", `#${p.toString()}`);
};

const DS_KEY = "doraDataSource";
function loadDataSource(): DataSource | null {
  try {
    const s = localStorage.getItem(DS_KEY);
    if (!s) return null;
    const d = JSON.parse(s);
    if (d && typeof d.name === "string" && d.kind) return d as DataSource;
  } catch {
    /* ignore */
  }
  return null;
}

export default function App() {
  const init = readHash();
  const [dataSrc, setDataSrc] = useState<DataSource | null>(loadDataSource);
  const [dsOpen, setDsOpen] = useState(false);
  const [, setSyncTick] = useState(0);
  const [page, setPage] = useState<Page>(init.page);
  const [type, setType] = useState<InsightType>(init.type);
  const [selected, setSelected] = useState(init.idx);
  const [drawer, setDrawer] = useState<Evidence | null>(null);
  const [cap, setCap] = useState<string | null>(null);
  const [toast, setToast] = useState("");
  const [joinedAction, setJoinedAction] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem("doraJoinedAction") || "[]");
    } catch {
      return [];
    }
  });
  const navigate = (p: Page, t = type, idx = selected) => {
    setPage(p);
    setType(t);
    setSelected(idx);
    writeHash(p, t, idx);
    window.scrollTo({
      top: 0,
      behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
    });
  };
  const toastTimer = useRef<number | undefined>(undefined);
  const notify = (msg: string) => {
    window.clearTimeout(toastTimer.current);
    setToast(msg);
    toastTimer.current = window.setTimeout(() => setToast(""), 4000);
  };
  useEffect(() => () => window.clearTimeout(toastTimer.current), []);
  const openTrace = async (id: string) => {
    try { const e = await getEvidence(id); setDrawer(e); }
    catch (err) { notify(`证据读取失败：${err instanceof Error ? err.message : String(err)}`); }
  };
  useEffect(() => {
    const onHash = () => {
      const x = readHash();
      setPage(x.page);
      setType(x.type);
      setSelected(x.idx);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => {
    localStorage.setItem("doraJoinedAction", JSON.stringify(joinedAction));
  }, [joinedAction]);
  useEffect(() => {
    if (dataSrc) {
      localStorage.setItem(DS_KEY, JSON.stringify(dataSrc));
    } else {
      localStorage.removeItem(DS_KEY);
    }
  }, [dataSrc]);
  useEffect(() => {
    if (!dataSrc) return;
    let alive = true;
    const refresh = async () => {
      await syncRemoteData();
      if (alive) setSyncTick((t) => t + 1);
    };
    void refresh();
    const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 20000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [dataSrc]);
  const onInsight = (t: InsightType, idx = 0) => navigate("insight", t, idx);
  const route = async (t: InsightType, id: string) => {
    if (t === "change") {
      navigate("watch");
      notify("已打开持续关注，请选择关注条件并确认创建委托");
      return;
    }
    try {
      // action-demo-separation：用户明确「加入行动回路」→ 认领已存在的演示档案（幂等）
      const r = await createAction(id, true);
      if (r.offline) {
        // 离线 = 未连后端、未确认建档（D047）：不谎报成功 —— 意图记入本机，由行动回路的「离线演示」分支如实展示
        setJoinedAction((p) => (p.includes(id) ? p : [...p, id]));
        navigate("action", t, 0);
        notify("✓ 已加入行动回路（离线演示：未连接后端，未确认建档；档案保存在本机）");
        return;
      }
      navigate("action", t, 0);
      notify(r.created ? `✓ 已建档并加入行动回路：${r.case?.code ?? id}` : `✓ 已加入行动回路（档案已存在）`);
    } catch (err) {
      // 后端明确拒绝（业务 4xx / http 模式未连后端）：展示原因，不伪造本地加入
      notify(`✗ 无法加入行动回路：${err instanceof Error ? err.message : String(err)}`);
    }
  };
  const handleReady = (ds: DataSource) => {
    setDataSrc(ds);
    navigate("pulse");
    notify(
      `✓ 数据就绪：${ds.name}（${ds.rows.toLocaleString()} 行 · ${ds.fields} 字段）；数据已接收，请查看分析结果`,
    );
  };
  const handleApply = (ds: DataSource) => {
    setDataSrc(ds);
    setDsOpen(false);
    navigate("pulse");
    notify(`✓ ${ds.name} 已更新；请查看最新分析结果`);
  };
  const handleClear = () => {
    setDataSrc(null);
    setDsOpen(false);
    navigate("pulse");
  };

  const refreshReasoning = async () => {
    let msg = "解释生成完成（模板模式）";
    try {
      const r = await refreshReasoningApi();
      msg =
        r.provider === "llm"
          ? "✓ AI 解释已重新生成"
          : r.updated.length > 0
            ? "✓ 解释已重新生成（模板模式）"
            : "解释刷新完成";
    } catch (err) {
      console.warn("[App] reasoning refresh failed", err);
      msg = "解释刷新失败，已保持模板解释";
    }
    try {
      const ok = await syncRemoteData();
      if (ok) setSyncTick((t) => t + 1);
    } catch (err) {
      console.warn("[App] reasoning resync failed", err);
    }
    notify(msg);
  };

  if (!dataSrc && page !== 'knowledge') return <OnboardingPage onReady={handleReady} onReadKnowledge={() => navigate('knowledge')} />;
  return (
    <div className="app">
      <Sidebar
        page={page}
        onPage={navigate}
        onCapability={setCap}
        onNotice={notify}
      />
      <main className="main">
        {page !== 'knowledge' && !dataConnection.online && <div className="note" role="status">{dataConnection.source === 'demo' ? '离线演示：当前为历史样例，不代表上传数据的分析结果' : '连接中断：当前为上次读取的数据，可能已过期'}</div>}
        <Topbar
          page={page}
          onTrace={() => openTrace("p1")}
          onNotice={notify}
          onUpdateData={() => dataSrc ? setDsOpen(true) : navigate("pulse")}
        />
        {page === "pulse" && (
          <PulsePage
            onPage={navigate}
            onInsight={onInsight}
            onTrace={openTrace}
            onNotice={notify}
            dataLabel={dataSrc ? `${dataSrc.name} · ${dataSrc.at} 更新` : ""}
          />
        )}{" "}
        {page === "insight" && (
          <InsightPage
            type={type}
            selected={selected}
            onType={(t) => onInsight(t)}
            onSelect={(i) => {
              setSelected(i);
              writeHash("insight", type, i);
            }}
            onTrace={openTrace}
            onRoute={route}
            onNotice={notify}
            onRefreshReasoning={refreshReasoning}
          />
        )}{" "}
        {page === "action" && (
          <ActionPage
            joined={joinedAction}
            onTrace={openTrace}
            onNotice={notify}
            onExecute={(id) =>
              notify(`✓ ${id} 执行任务已发起，结果将回写问题档案`)
            }
            onAddExpert={() => notify("✓ 已添加供应链专家")}
            onAddData={() => notify("✓ 已加入竞品价格数据")}
          />
        )}{" "}
        {page === "watch" && (
          <WatchPage
            onTrace={openTrace}
            onNotice={notify}
            onAction={() => navigate("action")}
            onInsight={(id) => {
              // watch-escalate-handoff：移交去向可能是 problem（如 p1）或 opportunity（如 o1），
              // 按真实洞察类型定位（原先只在 change 里找 → 会落到错列表第 0 项）
              const pi = insights.problem.findIndex((x) => x.id === id);
              if (pi >= 0) { onInsight("problem", pi); return; }
              const oi = insights.opportunity.findIndex((x) => x.id === id);
              if (oi >= 0) { onInsight("opportunity", oi); return; }
              const ci = insights.change.findIndex((x) => x.id === id);
              onInsight("change", ci >= 0 ? ci : 0);
            }}
          />
        )}
        {page === "knowledge" && <KnowledgePage />}
      </main>
      <EvidenceDrawer
        data={drawer}
        onClose={() => setDrawer(null)}
        onLocate={() => {
          const rows = document.querySelector('.drawer .raw');
          rows?.scrollIntoView({ behavior: 'smooth', block: 'center' });
          rows?.classList.add('located');
          notify('已定位到当前证据表；完整上传文件的历史版本尚未保存');
        }}
      />
      <CapabilityPanel name={cap} onClose={() => setCap(null)} />
      {dsOpen && dataSrc && (
        <DataSourceModal
          current={dataSrc}
          onClose={() => setDsOpen(false)}
          onApply={handleApply}
          onClear={handleClear}
        />
      )}
      {toast && (
        <div className="toast show" role="status" aria-live="polite">
          {toast}
        </div>
      )}
    </div>
  );
}
