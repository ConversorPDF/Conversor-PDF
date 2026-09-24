import { useRef, useState } from "react";
import type { DragEvent } from "react";
import { toast } from "sonner";
import { ArrowLeft, FileUp, Loader2, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError, apiUploadFile, downloadBlob } from "@/lib/api";
import type { Lang } from "@/lib/i18n";
import { translator } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import WaveformTrimmer from "@/components/WaveformTrimmer";

export interface SelectSpec {
  field: string;
  labelKey: string;
  default: string;
  options: { value: string; labelKey: string }[];
}

export interface ToolConfig {
  id: string;
  endpoint: string;
  titleKey: string;
  descKey: string;
  accept: string;
  multiple: boolean;
  minFiles: number;
  field: "file" | "files";
  category: "documents" | "image" | "audio" | "video";
  ranges?: boolean;
  select?: SelectSpec;
  bitrate?: boolean; // MP3/M4A quality selector (128/192/320)
  normalize?: boolean; // even-out loudness across tracks
  trim?: boolean; // start/end cut
}

const BITRATES = ["128", "192", "320"];

const MAX_BYTES = 100 * 1024 * 1024;

function humanSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface Props {
  tool: ToolConfig;
  lang: Lang;
  onBack: () => void;
}

export default function ToolPanel({ tool, lang, onBack }: Props) {
  const t = translator(lang);
  const [files, setFiles] = useState<File[]>([]);
  const [ranges, setRanges] = useState("");
  const [selectValue, setSelectValue] = useState(tool.select?.default ?? "");
  const [bitrate, setBitrate] = useState("192");
  const [normalize, setNormalize] = useState(false);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState(0);
  const [phase, setPhase] = useState<"idle" | "uploading" | "working">("idle");
  const inputRef = useRef<HTMLInputElement>(null);

  const busy = phase !== "idle";

  function addFiles(incoming: FileList | null) {
    if (!incoming) return;
    const list = Array.from(incoming);
    const ok = list.filter((f) => {
      if (f.size > MAX_BYTES) {
        toast.error(`${f.name}: ${t("errTooBig")}`);
        return false;
      }
      return true;
    });
    setFiles((prev) => (tool.multiple ? [...prev, ...ok] : ok.slice(0, 1)));
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
    if (busy) return;
    addFiles(e.dataTransfer.files);
  }

  async function run() {
    if (files.length < tool.minFiles) {
      toast.error(tool.minFiles > 1 ? t("errNeedTwo") : t("errNeedFiles"));
      return;
    }
    const form = new FormData();
    if (tool.field === "file") form.append("file", files[0]);
    else files.forEach((f) => form.append("files", f));
    if (tool.ranges) form.append("ranges", ranges);
    if (tool.select) form.append(tool.select.field, selectValue);
    if (tool.bitrate) form.append("bitrate", bitrate);
    if (tool.normalize) form.append("normalize", normalize ? "true" : "false");
    if (tool.trim) {
      form.append("start", start.trim());
      form.append("end", end.trim());
    }

    setPhase("uploading");
    setProgress(0);
    try {
      const result = await apiUploadFile(tool.endpoint, form, (p) => {
        setProgress(p);
        if (p >= 100) setPhase("working");
      });
      setPhase("idle");
      setProgress(100);
      downloadBlob(result);
      if (result.reductionPercent !== undefined) {
        toast.success(
          result.reductionPercent > 0
            ? t("reduction").replace("{n}", String(result.reductionPercent))
            : t("noReduction"),
        );
      } else {
        toast.success(t("done"));
      }
      setFiles([]);
      setRanges("");
      setStart("");
      setEnd("");
      if (inputRef.current) inputRef.current.value = "";
    } catch (err) {
      setPhase("idle");
      setProgress(0);
      const detail =
        err instanceof ApiError &&
        err.body &&
        typeof err.body === "object" &&
        "detail" in err.body
          ? String((err.body as { detail: unknown }).detail)
          : t("errGeneric");
      toast.error(detail);
    }
  }

  return (
    <section
      className="animate-rise rounded-2xl border border-border bg-card p-5 shadow-sm sm:p-8"
      data-testid="tool-panel"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="font-heading text-2xl font-bold tracking-tight" data-testid="tool-panel-title">
            {t(tool.titleKey)}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">{t(tool.descKey)}</p>
        </div>
        <Button variant="ghost" size="sm" onClick={onBack} data-testid="tool-panel-back-button">
          <ArrowLeft className="size-4" /> {t("back")}
        </Button>
      </div>

      <div
        role="button"
        tabIndex={0}
        onClick={() => !busy && inputRef.current?.click()}
        onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cn(
          "mt-6 flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-border bg-muted/40 px-6 py-12 text-center transition-[border-color,background-color,transform,box-shadow] duration-200",
          dragging && "scale-[1.01] border-primary bg-accent/40 shadow-lg",
          busy && "pointer-events-none opacity-60",
        )}
        data-testid="tool-dropzone"
      >
        <FileUp className="size-8 text-primary" />
        <p className="mt-3 font-heading text-base font-semibold">{t("dropTitle")}</p>
        <p className="text-sm text-muted-foreground">{t("dropHint")}</p>
        <p className="mt-3 font-mono text-xs text-muted-foreground">
          {t("accepts")}: {tool.accept}
        </p>
        <input
          ref={inputRef}
          type="file"
          className="hidden"
          accept={tool.accept}
          multiple={tool.multiple}
          onChange={(e) => addFiles(e.target.files)}
          data-testid="tool-file-input"
        />
      </div>

      {files.length > 0 && (
        <div className="mt-5" data-testid="tool-file-list">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {t("selected")} ({files.length})
            </p>
            <Button
              variant="ghost"
              size="xs"
              onClick={() => setFiles([])}
              data-testid="tool-clear-files-button"
            >
              <Trash2 className="size-3.5" /> {t("clear")}
            </Button>
          </div>
          <ul className="mt-2 divide-y divide-border rounded-xl border border-border">
            {files.map((f, i) => (
              <li
                key={`${f.name}-${i}`}
                className="flex items-center justify-between gap-3 px-4 py-2.5"
                data-testid="tool-file-item"
              >
                <span className="truncate text-sm">{f.name}</span>
                <span className="flex shrink-0 items-center gap-3">
                  <span className="font-mono text-xs text-muted-foreground">
                    {humanSize(f.size)}
                  </span>
                  <button
                    type="button"
                    aria-label={t("remove")}
                    onClick={() => setFiles((prev) => prev.filter((_, idx) => idx !== i))}
                    className="text-muted-foreground transition-colors duration-150 hover:text-destructive"
                    data-testid="tool-file-remove-button"
                  >
                    <X className="size-4" />
                  </button>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {tool.ranges && (
        <div className="mt-5 max-w-md">
          <Label htmlFor="ranges-input">{t("rangesLabel")}</Label>
          <Input
            id="ranges-input"
            value={ranges}
            onChange={(e) => setRanges(e.target.value)}
            placeholder="1-3, 5, 8-10"
            className="mt-1.5 font-mono"
            data-testid="tool-ranges-input"
          />
          <p className="mt-1.5 text-xs text-muted-foreground">{t("rangesHint")}</p>
        </div>
      )}

      {tool.select && (
        <div className="mt-5 max-w-md">
          <Label htmlFor="level-select">{t(tool.select.labelKey)}</Label>
          <Select value={selectValue} onValueChange={setSelectValue}>
            <SelectTrigger
              id="level-select"
              className="mt-1.5 w-full"
              data-testid="tool-select-trigger"
            >
              <SelectValue>
                {(v) => {
                  const opt = tool.select?.options.find((o) => o.value === (v as string));
                  return opt ? t(opt.labelKey) : "";
                }}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {tool.select.options.map((opt) => (
                <SelectItem
                  key={opt.value}
                  value={opt.value}
                  data-testid={`tool-select-option-${opt.value}`}
                >
                  {t(opt.labelKey)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {tool.bitrate && (selectValue === "mp3" || selectValue === "m4a") && (
        <div className="mt-5 max-w-md">
          <Label htmlFor="bitrate-select">{t("bitrateLabel")}</Label>
          <Select value={bitrate} onValueChange={setBitrate}>
            <SelectTrigger
              id="bitrate-select"
              className="mt-1.5 w-full"
              data-testid="tool-bitrate-trigger"
            >
              <SelectValue>{(v) => `${v as string} kbps`}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {BITRATES.map((b) => (
                <SelectItem key={b} value={b} data-testid={`tool-bitrate-option-${b}`}>
                  {b} kbps
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {tool.trim &&
        (files.length === 1 ? (
          <WaveformTrimmer
            key={`${files[0].name}-${files[0].size}`}
            file={files[0]}
            lang={lang}
            onChange={(s, e) => {
              setStart(s);
              setEnd(e);
            }}
          />
        ) : (
          <div className="mt-5 max-w-md">
            <Label>{t("trimLabel")}</Label>
            <div className="mt-1.5 flex items-center gap-3">
              <Input
                value={start}
                onChange={(e) => setStart(e.target.value)}
                placeholder={t("trimStart")}
                className="font-mono"
                data-testid="tool-trim-start"
              />
              <span className="text-muted-foreground">→</span>
              <Input
                value={end}
                onChange={(e) => setEnd(e.target.value)}
                placeholder={t("trimEnd")}
                className="font-mono"
                data-testid="tool-trim-end"
              />
            </div>
            <p className="mt-1.5 text-xs text-muted-foreground">{t("trimHint")}</p>
          </div>
        ))}

      {tool.normalize && (
        <label
          className="mt-5 flex max-w-md cursor-pointer items-start gap-3 rounded-xl border border-border bg-muted/30 p-4"
          data-testid="tool-normalize-label"
        >
          <Checkbox
            checked={normalize}
            onCheckedChange={(v) => setNormalize(v === true)}
            className="mt-0.5"
            data-testid="tool-normalize-checkbox"
          />
          <span>
            <span className="block text-sm font-medium">{t("normalizeLabel")}</span>
            <span className="block text-xs text-muted-foreground">{t("normalizeHint")}</span>
          </span>
        </label>
      )}

      {busy && (
        <div className="mt-6" data-testid="tool-progress">
          <div className="flex items-center justify-between text-xs font-medium">
            <span className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin" />
              {phase === "uploading" ? t("uploading") : t("working")}
            </span>
            <span className="font-mono">{phase === "uploading" ? `${progress}%` : "…"}</span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted">
            <div
              className={cn(
                "h-full rounded-full bg-primary transition-[width] duration-300 ease-out",
                phase === "working" && "animate-pulse",
              )}
              style={{ width: phase === "working" ? "100%" : `${Math.max(progress, 4)}%` }}
              data-testid="tool-progress-bar"
            />
          </div>
        </div>
      )}

      <Button
        className="mt-6 w-full sm:w-auto"
        size="lg"
        disabled={busy}
        onClick={run}
        data-testid="tool-run-button"
      >
        {busy ? t("processing") : t("run")}
      </Button>
    </section>
  );
}
