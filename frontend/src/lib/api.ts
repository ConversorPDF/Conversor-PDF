// Typed fetch layer over the FastAPI backend. Base is the relative "/api" prefix so the
// same code works in dev (Vite proxies /api → :8001) and behind a single origin in prod.
const BASE = "/api";

// Fields are declared, not constructor parameter properties: tsconfig sets
// erasableSyntaxOnly, which rejects `constructor(readonly status: number)`.
export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, body: unknown) {
    super(`request failed with ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

type JsonBody = unknown;

async function request<T>(method: string, path: string, body?: JsonBody): Promise<T> {
  // Auth rides the httpOnly session cookie automatically — never add auth headers here.
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  // FastAPI reports request-validation failures as 422 with a {detail: [...]} body.
  if (!res.ok) {
    const errBody = await res.json().catch(() => null);
    throw new ApiError(res.status, errBody);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// The response type is yours to declare: nothing infers across the Python boundary, so a
// TS interface here mirrors the endpoint's Pydantic model by hand — keep the two in sync.
export const apiGet = <T>(path: string) => request<T>("GET", path);
export const apiPost = <T>(path: string, body?: JsonBody) => request<T>("POST", path, body ?? null);
export const apiPut = <T>(path: string, body?: JsonBody) => request<T>("PUT", path, body ?? null);
export const apiPatch = <T>(path: string, body?: JsonBody) =>
  request<T>("PATCH", path, body ?? null);
export const apiDelete = <T>(path: string) => request<T>("DELETE", path);

export interface FileResult {
  blob: Blob;
  filename: string;
}

// Multipart upload returning a binary file, with upload-progress reporting (XHR: fetch
// cannot report upload progress). Still a relative /api path through the Vite proxy.
export function apiUploadFile(
  path: string,
  form: FormData,
  onProgress?: (percent: number) => void,
): Promise<FileResult> {
  return new Promise<FileResult>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}${path}`);
    xhr.responseType = "blob";

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100));
    };

    xhr.onerror = () => reject(new ApiError(0, null));

    xhr.onload = () => {
      const blob = xhr.response as Blob;
      if (xhr.status < 200 || xhr.status >= 300) {
        blob
          .text()
          .then((txt) => {
            let parsed: unknown = txt;
            try {
              parsed = JSON.parse(txt);
            } catch {
              /* plain text body */
            }
            reject(new ApiError(xhr.status, parsed));
          })
          .catch(() => reject(new ApiError(xhr.status, null)));
        return;
      }
      const disposition = xhr.getResponseHeader("Content-Disposition") ?? "";
      const match = /filename="?([^";]+)"?/.exec(disposition);
      resolve({ blob, filename: match ? match[1] : "resultado" });
    };

    xhr.send(form);
  });
}

export function downloadBlob(result: FileResult) {
  const url = URL.createObjectURL(result.blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = result.filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
