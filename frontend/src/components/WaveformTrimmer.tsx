import { useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { Lang } from "@/lib/i18n";
import { translator } from "@/lib/i18n";

const AUDIO_EXT = [".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".oga", ".opus", ".wma"];

function fmt(sec: number): string {
  if (!isFinite(sec) || sec < 0) return "0:00";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

interface Props {
  file: File;
  lang: Lang;
  onChange: (start: string, end: string) => void;
}

// Decodes the picked audio in-browser (Web Audio API — fully local) and lets the user drag
// the start/end handles over a waveform. Reports trim points (seconds) to the parent; an
// untouched edge is reported as "" so it means "no trim". Falls back to numeric inputs for
// non-audio inputs (e.g. video for the extract tool) or when decoding fails.
export default function WaveformTrimmer({ file, lang, onChange }: Props) {
  const t = translator(lang);
  const isAudio = AUDIO_EXT.some((e) => file.name.toLowerCase().endsWith(e));
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  });

  const [duration, setDuration] = useState(0);
  const [peaks, setPeaks] = useState<number[]>([]);
  const [failed, setFailed] = useState(!isAudio);
  const [sel, setSel] = useState<{ s: number; e: number }>({ s: 0, e: 0 });
  const [startTxt, setStartTxt] = useState("");
  const [endTxt, setEndTxt] = useState("");

  useEffect(() => {
    let cancelled = false;
    setFailed(!isAudio);
    setDuration(0);
    setPeaks([]);
    setSel({ s: 0, e: 0 });
    setStartTxt("");
    setEndTxt("");
    onChangeRef.current("", "");
    if (!isAudio) return;
    (async () => {
      try {
        const buf = await file.arrayBuffer();
        const Ctor =
          window.AudioContext ||
          (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
        const ctx = new Ctor();
        const audio = await ctx.decodeAudioData(buf.slice(0));
        ctx.close();
        if (cancelled) return;
        const ch = audio.getChannelData(0);
        const n = 400;
        const block = Math.floor(ch.length / n) || 1;
        const pk: number[] = [];
        for (let i = 0; i < n; i++) {
          let max = 0;
          const base = i * block;
          for (let j = 0; j < block; j++) {
            const v = Math.abs(ch[base + j] || 0);
            if (v > max) max = v;
          }
          pk.push(max);
        }
        setPeaks(pk);
        setDuration(audio.duration);
        setSel({ s: 0, e: audio.duration });
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [file, isAudio]);

  useEffect(() => {
    const c = canvasRef.current;
    const wrap = wrapRef.current;
    if (!c || !wrap || peaks.length === 0) return;
    const w = wrap.clientWidth;
    const h = 80;
    const dpr = window.devicePixelRatio || 1;
    c.width = w * dpr;
    c.height = h * dpr;
    c.style.width = `${w}px`;
    c.style.height = `${h}px`;
    const g = c.getContext("2d");
    if (!g) return;
    g.scale(dpr, dpr);
    g.clearRect(0, 0, w, h);
    const bw = w / peaks.length;
    for (let i = 0; i < peaks.length; i++) {
      const x = i * bw;
      const bh = Math.max(2, peaks[i] * h * 0.9);
      const y = (h - bh) / 2;
      const tsec = (i / peaks.length) * duration;
      const inSel = tsec >= sel.s && tsec <= sel.e;
      g.fillStyle = inSel ? "rgba(225,29,72,0.9)" : "rgba(148,163,184,0.45)";
      g.fillRect(x, y, Math.max(1, bw - 0.5), bh);
    }
  }, [peaks, sel, duration]);

  function emit(s: number, e: number) {
    const startStr = s <= 0.05 ? "" : s.toFixed(2);
    const endStr = e >= duration - 0.05 ? "" : e.toFixed(2);
    onChangeRef.current(startStr, endStr);
  }

  function startDrag(which: "s" | "e") {
    return (ev: ReactPointerEvent) => {
      ev.preventDefault();
      const wrap = wrapRef.current;
      if (!wrap) return;
      const rect = wrap.getBoundingClientRect();
      function move(e: PointerEvent) {
        const pct = (e.clientX - rect.left) / rect.width;
        const sec = Math.min(duration, Math.max(0, pct * duration));
        setSel((prev) => {
          let ns = prev.s;
          let ne = prev.e;
          if (which === "s") ns = Math.min(Math.max(0, sec), prev.e - 0.1);
          else ne = Math.max(Math.min(duration, sec), prev.s + 0.1);
          emit(ns, ne);
          return { s: ns, e: ne };
        });
      }
      function up() {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
      }
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    };
  }

  if (failed) {
    return (
      <div className="mt-5 max-w-md">
        <Label>{t("trimLabel")}</Label>
        <div className="mt-1.5 flex items-center gap-3">
          <Input
            value={startTxt}
            onChange={(e) => {
              setStartTxt(e.target.value);
              onChangeRef.current(e.target.value.trim(), endTxt.trim());
            }}
            placeholder={t("trimStart")}
            className="font-mono"
            data-testid="tool-trim-start"
          />
          <span className="text-muted-foreground">→</span>
          <Input
            value={endTxt}
            onChange={(e) => {
              setEndTxt(e.target.value);
              onChangeRef.current(startTxt.trim(), e.target.value.trim());
            }}
            placeholder={t("trimEnd")}
            className="font-mono"
            data-testid="tool-trim-end"
          />
        </div>
        <p className="mt-1.5 text-xs text-muted-foreground">{t("trimHint")}</p>
      </div>
    );
  }

  return (
    <div className="mt-5" data-testid="tool-waveform">
      <div className="flex items-center justify-between">
        <Label>{t("trimLabel")}</Label>
        <Button
          variant="ghost"
          size="xs"
          onClick={() => {
            setSel({ s: 0, e: duration });
            onChangeRef.current("", "");
          }}
          data-testid="tool-waveform-reset"
        >
          {t("waveReset")}
        </Button>
      </div>
      {peaks.length === 0 ? (
        <p className="mt-2 text-xs text-muted-foreground" data-testid="tool-waveform-loading">
          {t("waveLoading")}
        </p>
      ) : (
        <>
          <div
            ref={wrapRef}
            className="relative mt-2 h-20 w-full touch-none select-none overflow-hidden rounded-xl border border-border bg-muted/30"
          >
            <canvas ref={canvasRef} className="absolute inset-0" />
            <div
              className="absolute top-0 h-full w-1.5 -translate-x-1/2 cursor-ew-resize rounded bg-primary shadow"
              style={{ left: `${duration ? (sel.s / duration) * 100 : 0}%` }}
              onPointerDown={startDrag("s")}
              data-testid="tool-waveform-handle-start"
            />
            <div
              className="absolute top-0 h-full w-1.5 -translate-x-1/2 cursor-ew-resize rounded bg-primary shadow"
              style={{ left: `${duration ? (sel.e / duration) * 100 : 100}%` }}
              onPointerDown={startDrag("e")}
              data-testid="tool-waveform-handle-end"
            />
          </div>
          <p
            className="mt-1.5 font-mono text-xs text-muted-foreground"
            data-testid="tool-waveform-readout"
          >
            {fmt(sel.s)} → {fmt(sel.e)} · {t("waveSelection")}
          </p>
        </>
      )}
    </div>
  );
}
