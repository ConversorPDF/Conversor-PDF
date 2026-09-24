// Chunked upload: slices a file and streams each block to disk on the server, so nothing
// large is ever held in memory (browser or server). Reports real progress as bytes land.
import { ApiError } from "@/lib/api";

const BASE = "/api";
const CHUNK = 8 * 1024 * 1024; // 8 MB per block

function putChunk(
  uploadId: string,
  index: number,
  blob: Blob,
  onLoaded: (loaded: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", `${BASE}/tools/upload/${uploadId}/${index}`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onLoaded(e.loaded);
    };
    xhr.onerror = () => reject(new ApiError(0, null));
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new ApiError(xhr.status, null));
    };
    xhr.send(blob);
  });
}

function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

// Uploads one file in blocks. `onProgress` receives a 0..1 fraction for this file. Returns
// the server upload id to reference the assembled file in a processing request.
export async function uploadFileChunked(
  file: File,
  category: string,
  onProgress: (fraction: number) => void,
): Promise<string> {
  const uploadId = newId();
  const total = Math.max(1, Math.ceil(file.size / CHUNK));
  const size = Math.max(1, file.size);
  let base = 0;
  for (let i = 0; i < total; i++) {
    const slice = file.slice(i * CHUNK, Math.min(file.size, (i + 1) * CHUNK));
    await putChunk(uploadId, i, slice, (loaded) => {
      onProgress(Math.min(1, (base + loaded) / size));
    });
    base += slice.size;
    onProgress(Math.min(1, base / size));
  }
  const res = await fetch(`${BASE}/tools/upload/${uploadId}/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename: file.name, total, category }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new ApiError(res.status, err);
  }
  return uploadId;
}
