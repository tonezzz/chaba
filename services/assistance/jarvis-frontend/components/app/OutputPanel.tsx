import React, { RefObject } from "react";

import { ConnectionState, MessageLog } from "../../types";
import CarsPanel from "../CarsPanel";

export function OutputPanel(props: {
  leftFullscreen: boolean;
  volume: number;
  state: ConnectionState;
  handleFrame: (frame: string) => void;
  Visualizer: React.ComponentType<{ volume: number; active: boolean }>;
  CameraFeed: React.ComponentType<{ active: boolean; onFrame: (frame: string) => void }>;

  activeRightPanel: "output" | "cars" | "checklist";
  setActiveRightPanel: (v: "output" | "cars" | "checklist") => void;

  activeMedia: MessageLog | null;

  seqNotes: string;
  setSeqNotes: (v: string) => void;
  seqCompletedNotes: string;
  setSeqCompletedNotes: (v: string) => void;
  seqNextText: string | null;
  seqNextIndex: number | null;
  seqTemplate: string[] | null;
  seqError: string;
  seqBusy: boolean;
  handleSeqSuggest: () => void;
  handleSeqApply: () => void;
  handleSeqApplyByText: () => void;
  handleSeqApplyAll: () => void;

  liveServiceCurrent: any;

  activeOutputTab: "dialog" | "ui_log" | "ws_log" | "pending";
  setActiveOutputTab: (v: "dialog" | "ui_log" | "ws_log" | "pending") => void;

  outputScrollRef: RefObject<HTMLDivElement | null>;
  outputStickToBottomRef: RefObject<boolean>;
  outputChat: MessageLog[];

  uiLogText: string;
  loadUiLogFromLocalStorage: () => string;
  setUiLogText: (v: string) => void;

  wsLogErr: string;
  wsLogText: string;
  refreshWsLog: () => void;

  pendingErr: string;
  pendingActionBusy: boolean;
  pendingItems: any[];
  pendingSelectedId: string | null;
  pendingPreview: any | null;
  pendingAuthCode: string;
  setPendingAuthCode: (v: string) => void;
  pendingActionResult: any | null;
  queueGoogleRelink: () => Promise<void>;
  refreshPending: () => Promise<void>;
  queueBundlePublishReload: () => Promise<void>;
  previewPending: (cid: string) => Promise<void>;
  confirmPending: (cid: string) => Promise<void>;
  cancelPending: (cid: string) => Promise<void>;
  copyPendingJson: (v: any) => Promise<void>;
}) {
  const {
    leftFullscreen,
    volume,
    state,
    handleFrame,
    Visualizer,
    CameraFeed,
    activeRightPanel,
    setActiveRightPanel,
    activeMedia,
    seqNotes,
    setSeqNotes,
    seqCompletedNotes,
    setSeqCompletedNotes,
    seqNextText,
    seqNextIndex,
    seqTemplate,
    seqError,
    seqBusy,
    handleSeqSuggest,
    handleSeqApply,
    handleSeqApplyByText,
    handleSeqApplyAll,
    liveServiceCurrent,
    activeOutputTab,
    setActiveOutputTab,
    outputScrollRef,
    outputStickToBottomRef,
    outputChat,
    uiLogText,
    loadUiLogFromLocalStorage,
    setUiLogText,
    wsLogErr,
    wsLogText,
    refreshWsLog,
    pendingErr,
    pendingActionBusy,
    pendingItems,
    pendingSelectedId,
    pendingPreview,
    pendingAuthCode,
    setPendingAuthCode,
    pendingActionResult,
    queueGoogleRelink,
    refreshPending,
    queueBundlePublishReload,
    previewPending,
    confirmPending,
    cancelPending,
    copyPendingJson,
  } = props;

  return (
    <div className={`flex-1 p-4 md:p-6 flex flex-col gap-4 relative z-10 min-h-0 overflow-hidden ${leftFullscreen ? "hidden" : ""}`}>
      
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 flex-none h-[64px] min-h-[64px] max-h-[64px]">
        
        <div className="relative rounded-2xl border border-slate-700 bg-slate-900/50 flex items-center justify-center overflow-hidden">
          <div className="absolute top-3 left-4 text-[10px] text-cyan-500 font-hud tracking-widest uppercase">Audio Input Matrix</div>
          <div className="h-full aspect-square max-w-full">
            <Visualizer volume={volume} active={state === ConnectionState.CONNECTED} />
          </div>
        </div>

        
        <div className="relative rounded-2xl border border-slate-700 bg-slate-900/50 flex items-center justify-center p-1 overflow-hidden">
          <div className="absolute top-2 left-3 text-[10px] text-cyan-500 font-hud tracking-widest uppercase z-10">&nbsp;</div>
          <div className="w-full h-full flex items-center justify-center overflow-hidden">
            <div className="h-full aspect-video max-w-full">
              <CameraFeed active={state === ConnectionState.CONNECTED} onFrame={handleFrame} />
            </div>
            {!state && <div className="absolute inset-0 flex items-center justify-center text-slate-600 font-mono text-sm">System Offline</div>}
          </div>
        </div>
      </div>

      
      <div className="flex-1 rounded-2xl border border-slate-700 bg-slate-900/50 p-6 relative overflow-hidden min-h-0 flex flex-col">
        <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-cyan-500/50 to-transparent"></div>
        <div className="flex items-center justify-between gap-3">
          <div className="text-[10px] text-cyan-500 font-hud tracking-widest uppercase flex items-center gap-2">
            <span>{activeRightPanel === "cars" ? "Cars" : "Main Output Display"}</span>
            {activeRightPanel === "output" && activeMedia && (
              <span className="px-2 py-0.5 rounded bg-cyan-900/50 text-cyan-200 border border-cyan-700/50 text-[9px]">{(activeMedia as any).metadata?.type}</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setActiveRightPanel("output")}
              className={`text-[11px] font-mono px-3 py-1 rounded-lg border transition-colors ${
                activeRightPanel === "output"
                  ? "border-cyan-500/40 bg-cyan-950/30 text-cyan-200"
                  : "border-slate-700 bg-slate-950/30 text-slate-300 hover:bg-slate-800/40"
              }`}
            >
              Output
            </button>
            <button
              onClick={() => setActiveRightPanel("cars")}
              className={`text-[11px] font-mono px-3 py-1 rounded-lg border transition-colors ${
                activeRightPanel === "cars"
                  ? "border-cyan-500/40 bg-cyan-950/30 text-cyan-200"
                  : "border-slate-700 bg-slate-950/30 text-slate-300 hover:bg-slate-800/40"
              }`}
            >
              Cars
            </button>
            <button
              onClick={() => setActiveRightPanel("checklist")}
              className={`text-[11px] font-mono px-3 py-1 rounded-lg border transition-colors ${
                activeRightPanel === "checklist"
                  ? "border-cyan-500/40 bg-cyan-950/30 text-cyan-200"
                  : "border-slate-700 bg-slate-950/30 text-slate-300 hover:bg-slate-800/40"
              }`}
            >
              Checklist
            </button>
          </div>
        </div>

        <div className="flex-1 w-full flex flex-col mt-4 min-h-0">
          {activeRightPanel === "cars" ? (
            <div className="w-full h-full min-h-0 overflow-auto">
              <CarsPanel liveService={liveServiceCurrent} connectionState={state} />
            </div>
          ) : activeRightPanel === "checklist" ? (
            <div className="w-full h-full min-h-0 overflow-auto">
              <div className="text-[10px] text-cyan-500 font-hud tracking-widest uppercase mb-3">Sequential Checklist</div>
              <textarea
                value={seqNotes}
                onChange={(e) => setSeqNotes(e.target.value)}
                placeholder="Paste task notes with checklist here (e.g. - [ ] step)"
                className="w-full h-40 px-3 py-2 rounded-xl text-sm font-mono bg-slate-950 border border-slate-800 text-slate-200 placeholder:text-slate-600"
              />
              <textarea
                value={seqCompletedNotes}
                onChange={(e) => setSeqCompletedNotes(e.target.value)}
                placeholder="Optional: paste completed task notes blocks for template inference (separate blocks with a line containing ---)"
                className="w-full h-28 mt-3 px-3 py-2 rounded-xl text-sm font-mono bg-slate-950 border border-slate-800 text-slate-200 placeholder:text-slate-600"
              />
              <div className="mt-3 flex items-center flex-wrap gap-2">
                <button
                  onClick={() => void handleSeqSuggest()}
                  disabled={seqBusy}
                  className="px-3 py-2 rounded-xl border border-cyan-500/40 bg-cyan-950/20 text-cyan-200 hover:bg-cyan-950/40 disabled:opacity-50 text-xs font-mono"
                >
                  Suggest
                </button>
                <button
                  onClick={() => void handleSeqApply()}
                  disabled={seqBusy || seqNextIndex == null}
                  className="px-3 py-2 rounded-xl border border-slate-700 bg-slate-950/30 text-slate-200 hover:bg-slate-800/40 disabled:opacity-50 text-xs font-mono"
                >
                  Apply
                </button>
                <button
                  onClick={() => void handleSeqApplyByText()}
                  disabled={seqBusy || !seqNextText}
                  className="px-3 py-2 rounded-xl border border-slate-700 bg-slate-950/30 text-slate-200 hover:bg-slate-800/40 disabled:opacity-50 text-xs font-mono"
                >
                  Apply by text
                </button>
                <button
                  onClick={() => void handleSeqApplyAll()}
                  disabled={seqBusy}
                  className="px-3 py-2 rounded-xl border border-slate-700 bg-slate-950/30 text-slate-200 hover:bg-slate-800/40 disabled:opacity-50 text-xs font-mono"
                >
                  Apply all
                </button>
                {seqError && <div className="text-xs font-mono text-red-400 truncate">{seqError}</div>}
              </div>
              <div className="mt-3 text-xs font-mono text-slate-300">
                <div>
                  next_step: {seqNextText ?? "(none)"}
                  {seqNextIndex != null ? ` (index=${seqNextIndex})` : ""}
                </div>
                <div>template: {seqTemplate ? seqTemplate.join(" | ") : "(none)"}</div>
              </div>
            </div>
          ) : (
            <div className="w-full flex-1 min-h-0 flex flex-col animate-in zoom-in-95 duration-500">
              <div className="w-full bg-slate-950/40 rounded-lg border border-slate-700 p-4 overflow-auto flex-1 min-h-0">
                <div className="sticky top-0 z-10 -mx-4 px-4 pt-1 pb-2 bg-slate-950/70 backdrop-blur border-b border-slate-800/60 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setActiveOutputTab("dialog")}
                      className={`text-[11px] font-mono px-3 py-1 rounded-lg border transition-colors ${
                        activeOutputTab === "dialog"
                          ? "border-cyan-500/40 bg-cyan-950/30 text-cyan-200"
                          : "border-slate-700 bg-slate-950/30 text-slate-300 hover:bg-slate-800/40"
                      }`}
                    >
                      Dialog
                    </button>
                    <button
                      onClick={() => setActiveOutputTab("ui_log")}
                      className={`text-[11px] font-mono px-3 py-1 rounded-lg border transition-colors ${
                        activeOutputTab === "ui_log"
                          ? "border-cyan-500/40 bg-cyan-950/30 text-cyan-200"
                          : "border-slate-700 bg-slate-950/30 text-slate-300 hover:bg-slate-800/40"
                      }`}
                    >
                      UI Log
                    </button>
                    <button
                      onClick={() => {
                        setActiveOutputTab("pending");
                        void refreshPending();
                      }}
                      className={`text-[11px] font-mono px-3 py-1 rounded-lg border transition-colors ${
                        activeOutputTab === "pending"
                          ? "border-cyan-500/40 bg-cyan-950/30 text-cyan-200"
                          : "border-slate-700 bg-slate-950/30 text-slate-300 hover:bg-slate-800/40"
                      }`}
                    >
                      Pending
                    </button>
                    <button
                      onClick={() => {
                        setActiveOutputTab("ws_log");
                        void refreshWsLog();
                      }}
                      className={`text-[11px] font-mono px-3 py-1 rounded-lg border transition-colors ${
                        activeOutputTab === "ws_log"
                          ? "border-cyan-500/40 bg-cyan-950/30 text-cyan-200"
                          : "border-slate-700 bg-slate-950/30 text-slate-300 hover:bg-slate-800/40"
                      }`}
                    >
                      Backend WS Log
                    </button>
                  </div>
                  <div className="flex items-center gap-2">
                    {activeOutputTab === "ui_log" && (
                      <button
                        onClick={() => {
                          const txt = loadUiLogFromLocalStorage();
                          setUiLogText(txt);
                        }}
                        className="text-[11px] font-mono px-3 py-1 rounded-lg border border-slate-700 bg-slate-950/30 text-slate-300 hover:bg-slate-800/40"
                      >
                        refresh
                      </button>
                    )}
                  </div>
                </div>

                {activeOutputTab === "dialog" && (activeMedia as any)?.metadata?.image ? (
                  <div className="relative group max-w-full max-h-full mt-3">
                    <img
                      src={(activeMedia as any).metadata.image}
                      alt="Generated content"
                      className="max-h-[400px] w-auto rounded-lg shadow-2xl border border-slate-600"
                    />
                    <div className="absolute bottom-2 right-2 bg-black/70 text-white text-xs px-2 py-1 rounded backdrop-blur font-mono">
                      Generated by Gemini
                    </div>
                  </div>
                ) : activeOutputTab === "dialog" && (activeMedia as any)?.metadata?.sources ? (
                  <div className="w-full bg-slate-800/50 rounded-lg border border-slate-700 p-4 overflow-auto mt-3">
                    <h3 className="text-cyan-400 font-hud text-sm mb-3 uppercase tracking-wider">Grounding Sources</h3>
                    <ul className="space-y-2">
                      {(activeMedia as any).metadata.sources.map((src: any, i: number) => (
                        <li key={i} className="flex items-start gap-3 p-2 rounded hover:bg-slate-700/50 transition-colors">
                          <span className="bg-slate-700 text-slate-300 text-xs w-5 h-5 flex items-center justify-center rounded-full flex-shrink-0 font-mono">
                            {i + 1}
                          </span>
                          <a
                            href={src.uri}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-sm text-cyan-300 hover:text-cyan-200 hover:underline truncate"
                          >
                            {src.title}
                          </a>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : activeOutputTab === "dialog" ? (
                  <div
                    ref={outputScrollRef}
                    className="w-full overflow-auto flex-1 min-h-0 mt-3"
                    onScroll={(e) => {
                      const el = e.currentTarget;
                      const remaining = el.scrollHeight - el.scrollTop - el.clientHeight;
                      outputStickToBottomRef.current = remaining < 40;
                    }}
                  >
                    <div className="flex flex-col gap-2">
                      {outputChat.length === 0 ? (
                        <div className="text-slate-600 font-mono text-sm">(no text yet)</div>
                      ) : (
                        outputChat.map((m: any) => {
                          const role = String(m.role || "");
                          const isUser = role === "user";
                          const isSystem = role === "system";
                          const align = isSystem ? "items-center" : isUser ? "items-end" : "items-start";
                          const bubble = isSystem
                            ? "bg-slate-900/40 border border-slate-700/60 text-slate-200"
                            : isUser
                              ? "bg-cyan-950/30 border border-cyan-600/30 text-cyan-50"
                              : "bg-slate-900/60 border border-slate-700/60 text-slate-100";
                          return (
                            <div
                              key={String(m.id || "") + "_" + String(m.timestamp?.getTime?.() || 0)}
                              className={`flex flex-col ${align}`}
                            >
                              <div
                                className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm font-mono whitespace-pre-wrap break-words leading-relaxed ${bubble}`}
                              >
                                {String(m.text || "").trim()}
                              </div>
                            </div>
                          );
                        })
                      )}
                    </div>
                  </div>
                ) : activeOutputTab === "ui_log" ? (
                  <pre className="text-[12px] font-mono text-slate-200 whitespace-pre-wrap mt-3">{uiLogText || "(empty)"}</pre>
                ) : activeOutputTab === "pending" ? (
                  <div className="flex flex-col gap-3 mt-3">
                    {pendingErr && (
                      <div className="text-[12px] font-mono text-red-300 border border-red-900/40 bg-red-950/20 rounded-lg px-3 py-2">
                        {pendingErr}
                      </div>
                    )}
                    <div className="flex items-center justify-between">
                      <div className="text-[12px] font-mono text-slate-400">pending</div>
                      <div className="flex items-center gap-2">
                        <button
                          disabled={pendingActionBusy}
                          onClick={() => void queueGoogleRelink()}
                          className="text-[11px] font-mono px-2 py-1 rounded border border-amber-700/40 bg-amber-950/20 text-amber-200 hover:bg-amber-900/30 disabled:opacity-50"
                        >
                          queue google relink
                        </button>
                        <button
                          disabled={pendingActionBusy}
                          onClick={() => void refreshPending()}
                          className="text-[11px] font-mono px-2 py-1 rounded border border-slate-700 bg-slate-950/30 text-slate-300 hover:bg-slate-800/40 disabled:opacity-50"
                        >
                          refresh
                        </button>
                      </div>
                    </div>
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-[12px] font-mono text-slate-400">pending writes: {pendingItems.length}</div>
                      <div className="flex items-center gap-2">
                        <button
                          disabled={pendingActionBusy}
                          onClick={() => void refreshPending()}
                          className="text-[11px] font-mono px-2 py-1 rounded border border-slate-700 bg-slate-950/30 text-slate-300 hover:bg-slate-800/40 disabled:opacity-50"
                        >
                          refresh
                        </button>
                        <button
                          disabled={pendingActionBusy}
                          onClick={() => void queueBundlePublishReload()}
                          className="text-[11px] font-mono px-2 py-1 rounded border border-cyan-700/40 bg-cyan-950/20 text-cyan-200 hover:bg-cyan-900/30 disabled:opacity-50"
                        >
                          bundle publish + reload
                        </button>
                      </div>
                    </div>
                    <div className="grid grid-cols-1 gap-2">
                      {pendingItems.length === 0 ? (
                        <div className="text-slate-600 font-mono text-sm">(none)</div>
                      ) : (
                        pendingItems.map((it: any) => {
                          const cid = String(it?.confirmation_id || "");
                          const selected = cid && pendingSelectedId === cid;
                          const action = String(it?.action || "");
                          const created = it?.created_at ? new Date(Number(it.created_at) * 1000).toLocaleString() : "";
                          return (
                            <div
                              key={cid || Math.random()}
                              className={`rounded-lg border px-3 py-2 ${
                                selected ? "border-cyan-500/40 bg-cyan-950/10" : "border-slate-800 bg-slate-950/20"
                              }`}
                            >
                              <div className="flex items-center justify-between gap-2">
                                <div className="min-w-0">
                                  <div className="text-[12px] font-mono text-slate-200 truncate">{cid}</div>
                                  <div className="text-[11px] font-mono text-slate-500">
                                    {action}
                                    {created ? ` • ${created}` : ""}
                                  </div>
                                </div>
                                <div className="flex items-center gap-2 shrink-0">
                                  <button
                                    disabled={!cid || pendingActionBusy}
                                    onClick={() => void previewPending(cid)}
                                    className="text-[11px] font-mono px-2 py-1 rounded border border-slate-700 bg-slate-950/30 text-slate-300 hover:bg-slate-800/40 disabled:opacity-50"
                                  >
                                    preview
                                  </button>
                                  <button
                                    disabled={!cid || pendingActionBusy}
                                    onClick={() => void confirmPending(cid)}
                                    className="text-[11px] font-mono px-2 py-1 rounded border border-cyan-700/40 bg-cyan-950/20 text-cyan-200 hover:bg-cyan-900/30 disabled:opacity-50"
                                  >
                                    confirm
                                  </button>
                                  <button
                                    disabled={!cid || pendingActionBusy}
                                    onClick={() => void cancelPending(cid)}
                                    className="text-[11px] font-mono px-2 py-1 rounded border border-slate-700 bg-slate-950/30 text-slate-300 hover:bg-slate-800/40 disabled:opacity-50"
                                  >
                                    cancel
                                  </button>
                                </div>
                              </div>
                              {selected && (
                                <div className="mt-2 grid grid-cols-1 gap-2">
                                  {pendingPreview && (
                                    <div className="border border-slate-800 rounded-lg bg-slate-950/20 px-3 py-2">
                                      <div className="flex items-center justify-between gap-2 mb-2">
                                        <div className="text-[10px] font-mono text-slate-500">preview json</div>
                                        <button
                                          onClick={() => void copyPendingJson(pendingPreview)}
                                          className="text-[11px] font-mono px-2 py-1 rounded border border-slate-700 bg-slate-950/30 text-slate-300 hover:bg-slate-800/40"
                                        >
                                          copy
                                        </button>
                                      </div>
                                      <pre className="text-[11px] font-mono text-slate-300 whitespace-pre-wrap">
                                        {JSON.stringify(pendingPreview, null, 2)}
                                      </pre>
                                    </div>
                                  )}

                                  {pendingPreview && String((pendingPreview as any).action || "") === "google_account_relink" && (
                                    <div className="border border-slate-800 rounded-lg bg-slate-950/10 px-3 py-2">
                                      <div className="text-[10px] font-mono text-slate-500 mb-2">google relink</div>
                                      <div className="text-[11px] font-mono text-slate-300 mb-2 break-words">
                                        {String((pendingPreview as any)?.details?.auth_url || "")}
                                      </div>
                                      <div className="flex items-center gap-2 mb-3 flex-wrap">
                                        <button
                                          onClick={() => void copyPendingJson(String((pendingPreview as any)?.details?.auth_url || ""))}
                                          className="text-[11px] font-mono px-2 py-1 rounded border border-slate-700 bg-slate-950/30 text-slate-300 hover:bg-slate-800/40"
                                        >
                                          copy url
                                        </button>
                                        <a
                                          href={String((pendingPreview as any)?.details?.auth_url || "")}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                          className="text-[11px] font-mono px-2 py-1 rounded border border-cyan-700/40 bg-cyan-950/20 text-cyan-200 hover:bg-cyan-900/30"
                                        >
                                          open url
                                        </a>
                                      </div>
                                      <input
                                        value={pendingAuthCode}
                                        onChange={(e) => setPendingAuthCode(e.target.value)}
                                        placeholder="Paste redirected URL (or code)"
                                        className="w-full px-3 py-2 rounded-lg text-xs font-mono bg-slate-950 border border-slate-800 text-slate-200 placeholder:text-slate-600"
                                      />
                                    </div>
                                  )}

                                  {pendingActionResult != null && (
                                    <div className="border border-slate-800 rounded-lg bg-slate-950/10 px-3 py-2">
                                      <div className="flex items-center justify-between gap-2 mb-2">
                                        <div className="text-[10px] font-mono text-slate-500">result json</div>
                                        <button
                                          onClick={() => void copyPendingJson(pendingActionResult)}
                                          className="text-[11px] font-mono px-2 py-1 rounded border border-slate-700 bg-slate-950/30 text-slate-300 hover:bg-slate-800/40"
                                        >
                                          copy
                                        </button>
                                      </div>
                                      <pre className="text-[11px] font-mono text-slate-400 whitespace-pre-wrap">
                                        {JSON.stringify(pendingActionResult, null, 2)}
                                      </pre>
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          );
                        })
                      )}
                    </div>
                  </div>
                ) : (
                  <>
                    {wsLogErr && <div className="text-[12px] font-mono text-red-300 mb-2 mt-3">{wsLogErr}</div>}
                    <pre className="text-[12px] font-mono text-slate-200 whitespace-pre-wrap mt-3">{wsLogText || "(empty)"}</pre>
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
