import React, { useCallback, useRef } from "react";
import { ConnectionState } from "../../types";
import type { Attachment } from "./types";

export function useAttachments(
  liveService: React.RefObject<import("../../services/liveService").LiveService | null>,
  state: ConnectionState,
  setAttachments: React.Dispatch<React.SetStateAction<Attachment[]>>
) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const handlePickFiles = useCallback(() => {
    if (state !== ConnectionState.CONNECTED) return;
    fileInputRef.current?.click();
  }, [state]);

  const handleRemoveAttachment = useCallback(
    (id: string) => {
      setAttachments((prev) => prev.filter((a) => a.id !== id));
    },
    [setAttachments]
  );

  const handleFilesSelected = useCallback(
    async (files: FileList | null) => {
      if (!files || files.length === 0) return;
      const next: Attachment[] = [];

      for (const f of Array.from(files)) {
        const name = String(f.name || "file");
        const size = Number(f.size || 0);
        const type = String(f.type || "");
        const isPdf = type === "application/pdf" || name.toLowerCase().endsWith(".pdf");
        const isImage = type.startsWith("image/");
        const isText = type.startsWith("text/") || name.toLowerCase().endsWith(".md") || name.toLowerCase().endsWith(".json");

        if (!isPdf && !isImage && !isText) {
          console.warn("Unsupported file type:", type, name);
          continue;
        }

        const id = `${Date.now()}_${Math.random().toString(16).slice(2)}`;

        if (isText) {
          try {
            const text = await f.text();
            next.push({ id, name, size, kind: "text", text });
          } catch {
            console.warn("Failed to read text file:", name);
          }
          continue;
        }

        if (isImage) {
          const base64 = await new Promise<string>((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => {
              const result = String(reader.result || "");
              const idx = result.indexOf(",");
              resolve(idx >= 0 ? result.slice(idx + 1) : result);
            };
            reader.onerror = reject;
            reader.readAsDataURL(f);
          });
          liveService.current?.addAttachment(id, base64, { mimeType: type, fileName: name });
          next.push({ id, name, size, kind: "image" });
          continue;
        }

        if (isPdf) {
          const base64 = await new Promise<string>((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => {
              const result = String(reader.result || "");
              const idx = result.indexOf(",");
              resolve(idx >= 0 ? result.slice(idx + 1) : result);
            };
            reader.onerror = reject;
            reader.readAsDataURL(f);
          });
          liveService.current?.addAttachment(id, base64, { mimeType: "application/pdf", fileName: name });
          next.push({ id, name, size, kind: "pdf" });
          continue;
        }
      }

      if (next.length > 0) {
        setAttachments((prev) => [...prev, ...next]);
      }
    },
    [liveService, setAttachments]
  );

  return {
    handlePickFiles,
    handleRemoveAttachment,
    handleFilesSelected,
    fileInputRef,
  };
}
