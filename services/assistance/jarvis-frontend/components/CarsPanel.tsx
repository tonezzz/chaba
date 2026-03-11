import React, { useCallback, useMemo, useRef, useState } from "react";
import { ConnectionState } from "../types";
import type { LiveService, CarsIngestResult } from "../services/liveService";
import { Paperclip, RefreshCcw } from "lucide-react";

type Props = {
  liveService: LiveService | null;
  connectionState: ConnectionState;
};

export default function CarsPanel({ liveService, connectionState }: Props) {
  const [lastResult, setLastResult] = useState<CarsIngestResult | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const canSend = connectionState === ConnectionState.CONNECTED && !!liveService && !isBusy;

  const handlePick = () => {
    if (!canSend) return;
    fileInputRef.current?.click();
  };

  const handleFiles = useCallback(
    async (files: FileList | null) => {
      if (!files || files.length === 0) return;
      if (!liveService) return;
      const f = files[0];
      if (!f) return;

      const type = String(f.type || "");
      const isImage = type.startsWith("image/") || /\.(png|jpe?g|webp)$/i.test(f.name);
      if (!isImage) {
        setError("unsupported_file_type");
        return;
      }
      if (f.size > 8 * 1024 * 1024) {
        setError("image_too_large(8MB)");
        return;
      }

      setError(null);
      setIsBusy(true);
      setLastResult(null);

      const requestId = `cars_${Date.now()}_${Math.random().toString(16).slice(2)}`;

      const onResult = (ev: CarsIngestResult) => {
        if (ev.request_id !== requestId) return;
        setLastResult(ev);
        setIsBusy(false);
      };

      liveService.onCarsIngestResult = onResult;

      try {
        await liveService.sendCarsIngestImage(f, requestId);
      } catch (e) {
        setIsBusy(false);
        setError(String((e as any)?.message || e));
      }
    },
    [liveService]
  );

  const items = useMemo(() => {
    const it = lastResult?.items;
    return Array.isArray(it) ? it : [];
  }, [lastResult]);

  return (
    <div className="w-full h-full flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-hud tracking-widest uppercase text-cyan-300">Cars</div>
          <div className="text-xs font-mono text-slate-500">Upload an exterior photo to extract Thai plates and persist records.</div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handlePick}
            disabled={!canSend}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-xl border border-slate-700 bg-slate-950/40 text-slate-200 hover:bg-slate-800/60 disabled:opacity-50 disabled:hover:bg-slate-950/40"
          >
            <Paperclip className="w-4 h-4" />
            Upload
          </button>
          <button
            onClick={() => setLastResult(null)}
            disabled={isBusy}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-xl border border-slate-700 bg-slate-950/40 text-slate-200 hover:bg-slate-800/60 disabled:opacity-50 disabled:hover:bg-slate-950/40"
          >
            <RefreshCcw className="w-4 h-4" />
            Clear
          </button>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => {
            void handleFiles(e.target.files);
            e.currentTarget.value = "";
          }}
        />
      </div>

      {connectionState !== ConnectionState.CONNECTED && (
        <div className="text-sm font-mono text-yellow-300/90 border border-yellow-500/30 bg-yellow-950/20 rounded-xl p-3">
          Connect Jarvis first to enable uploads.
        </div>
      )}

      {isBusy && (
        <div className="text-sm font-mono text-cyan-200 border border-cyan-500/30 bg-cyan-950/20 rounded-xl p-3">
          Uploading + scanning...
        </div>
      )}

      {error && (
        <div className="text-sm font-mono text-red-300 border border-red-500/30 bg-red-950/20 rounded-xl p-3">
          {error}
        </div>
      )}

      {lastResult && (
        <div className="border border-slate-800 bg-slate-950/30 rounded-2xl p-4 overflow-auto">
          <div className="text-xs font-mono text-slate-400 mb-2">request_id: {lastResult.request_id}</div>
          <div className="text-xs font-mono text-slate-400 mb-4">original_path: {lastResult.original_path}</div>

          {items.length === 0 ? (
            <div className="text-sm font-mono text-slate-400">No plates detected. (Check GEMINI_API_KEY on backend.)</div>
          ) : (
            <div className="space-y-3">
              {items.map((it, idx) => (
                <div key={`${it.plate || "plate"}_${idx}`} className="rounded-xl border border-slate-800 bg-slate-900/30 p-3">
                  <div className="flex items-center justify-between gap-4">
                    <div className="text-sm font-hud text-cyan-200 tracking-wider">{it.plate}</div>
                    <div className="text-[11px] font-mono text-slate-500">confidence={it.confidence ?? ""}</div>
                  </div>
                  <div className="mt-2 text-[11px] font-mono text-slate-400">json: {it.json_path}</div>
                  {it.plate_crop && <div className="mt-1 text-[11px] font-mono text-slate-500">plate_crop: {it.plate_crop}</div>}
                  {it.car_crop && <div className="mt-1 text-[11px] font-mono text-slate-500">car_crop: {it.car_crop}</div>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
