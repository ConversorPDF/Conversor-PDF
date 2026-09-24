import { useState } from "react";
import {
  FileText,
  FileType2,
  HardDrive,
  Image as ImageIcon,
  Images,
  Layers,
  Minimize2,
  Scissors,
  ShieldCheck,
  Trash,
} from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Toaster } from "@/components/ui/sonner";
import ToolPanel from "@/components/ToolPanel";
import type { ToolConfig } from "@/components/ToolPanel";
import type { Lang } from "@/lib/i18n";
import { getLang, setLang, translator } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const TOOLS: ToolConfig[] = [
  {
    id: "word-to-pdf",
    endpoint: "/tools/word-to-pdf",
    titleKey: "w2p",
    descKey: "w2pDesc",
    accept: ".docx,.doc,.odt,.rtf",
    multiple: true,
    minFiles: 1,
    field: "files",
    category: "documents",
  },
  {
    id: "pdf-to-word",
    endpoint: "/tools/pdf-to-word",
    titleKey: "p2w",
    descKey: "p2wDesc",
    accept: ".pdf",
    multiple: false,
    minFiles: 1,
    field: "file",
    category: "documents",
  },
  {
    id: "merge-pdf",
    endpoint: "/tools/merge-pdf",
    titleKey: "merge",
    descKey: "mergeDesc",
    accept: ".pdf",
    multiple: true,
    minFiles: 2,
    field: "files",
    category: "documents",
  },
  {
    id: "split-pdf",
    endpoint: "/tools/split-pdf",
    titleKey: "split",
    descKey: "splitDesc",
    accept: ".pdf",
    multiple: false,
    minFiles: 1,
    field: "file",
    category: "documents",
    ranges: true,
  },
  {
    id: "compress-pdf",
    endpoint: "/tools/compress-pdf",
    titleKey: "compress",
    descKey: "compressDesc",
    accept: ".pdf",
    multiple: false,
    minFiles: 1,
    field: "file",
    category: "documents",
    select: {
      field: "level",
      labelKey: "levelLabel",
      default: "recomendada",
      options: [
        { value: "ligera", labelKey: "levelLigera" },
        { value: "recomendada", labelKey: "levelRecomendada" },
        { value: "maxima", labelKey: "levelMaxima" },
      ],
    },
  },
  {
    id: "convert-image",
    endpoint: "/tools/convert-image",
    titleKey: "convertImg",
    descKey: "convertImgDesc",
    accept: ".jpg,.jpeg,.png,.bmp,.webp,.tif,.tiff",
    multiple: true,
    minFiles: 1,
    field: "files",
    category: "image",
    select: {
      field: "target",
      labelKey: "targetLabel",
      default: "png",
      options: [
        { value: "png", labelKey: "targetPng" },
        { value: "jpg", labelKey: "targetJpg" },
      ],
    },
  },
  {
    id: "images-to-pdf",
    endpoint: "/tools/images-to-pdf",
    titleKey: "img",
    descKey: "imgDesc",
    accept: ".jpg,.jpeg,.png,.webp",
    multiple: true,
    minFiles: 1,
    field: "files",
    category: "image",
  },
];

const ICONS: Record<string, typeof FileText> = {
  "word-to-pdf": FileText,
  "pdf-to-word": FileType2,
  "merge-pdf": Layers,
  "split-pdf": Scissors,
  "images-to-pdf": Images,
  "compress-pdf": Minimize2,
  "convert-image": ImageIcon,
};

const TABS: { id: "documents" | "image"; labelKey: string }[] = [
  { id: "documents", labelKey: "tabDocuments" },
  { id: "image", labelKey: "tabImage" },
];

export default function Home() {
  const [lang, setLangState] = useState<Lang>(() => getLang());
  const [activeId, setActiveId] = useState<string | null>(null);
  const [tab, setTab] = useState<"documents" | "image">("documents");
  const t = translator(lang);
  const active = TOOLS.find((x) => x.id === activeId) ?? null;

  function changeLang(next: Lang) {
    setLangState(next);
    setLang(next);
  }

  function selectTab(next: string) {
    setTab(next as "documents" | "image");
    setActiveId(null); // collapse any open panel when switching category
  }

  return (
    <div className="min-h-screen bg-background">
      <Toaster richColors />

      <header className="sticky top-0 z-50 w-full border-b border-border bg-background/85 backdrop-blur-xl">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-5 py-3.5">
          <div className="flex items-center gap-2.5">
            <span className="grid size-9 place-items-center rounded-lg bg-primary text-primary-foreground">
              <FileText className="size-5" />
            </span>
            <div className="leading-tight">
              <p className="font-heading text-base font-extrabold tracking-tight" data-testid="app-brand">
                {t("brand")}
              </p>
              <p className="text-xs text-muted-foreground">{t("tagline")}</p>
            </div>
          </div>
          <div
            className="flex items-center gap-1 rounded-full border border-border bg-card p-1"
            role="group"
            aria-label={t("langLabel")}
          >
            {(["es", "ca"] as Lang[]).map((code) => (
              <button
                key={code}
                type="button"
                onClick={() => changeLang(code)}
                className={cn(
                  "rounded-full px-3 py-1 text-xs font-semibold uppercase transition-colors duration-150",
                  lang === code
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
                data-testid={`lang-switch-${code}`}
              >
                {code}
              </button>
            ))}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-5 pb-20 pt-10">
        <section className="max-w-2xl">
          <h1
            className="font-heading text-3xl font-extrabold leading-tight tracking-tight sm:text-4xl lg:text-5xl"
            data-testid="hero-title"
          >
            {t("heroTitle")}
          </h1>
          <p className="mt-4 text-sm leading-relaxed text-muted-foreground sm:text-base">
            {t("heroBody")}
          </p>
          <div className="mt-5 flex flex-wrap gap-2 text-xs font-medium">
            {[
              { icon: ShieldCheck, label: t("badgeLocal") },
              { icon: HardDrive, label: t("badgeLimit") },
              { icon: Trash, label: t("badgeClean") },
            ].map(({ icon: Icon, label }) => (
              <span
                key={label}
                className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1.5 text-muted-foreground"
              >
                <Icon className="size-3.5 text-primary" />
                {label}
              </span>
            ))}
          </div>
        </section>

        <section className="mt-12">
          <Tabs value={tab} onValueChange={selectTab}>
            <TabsList variant="line" data-testid="category-tabs">
              {TABS.map((tb) => (
                <TabsTrigger key={tb.id} value={tb.id} data-testid={`tab-${tb.id}`}>
                  {t(tb.labelKey)}
                </TabsTrigger>
              ))}
            </TabsList>

            {TABS.map((tb) => {
              const tools = TOOLS.filter((x) => x.category === tb.id);
              return (
                <TabsContent key={tb.id} value={tb.id} className="mt-6">
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {tools.map((tool) => {
                      const Icon = ICONS[tool.id];
                      const selected = tool.id === activeId;
                      return (
                        <button
                          key={tool.id}
                          type="button"
                          onClick={() => setActiveId(tool.id)}
                          className={cn(
                            "group rounded-xl border border-border bg-card p-5 text-left transition-[transform,box-shadow,border-color] duration-200 hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-md",
                            selected && "border-primary shadow-md ring-4 ring-primary/10",
                          )}
                          data-testid={`tool-card-${tool.id}`}
                        >
                          <span className="grid size-10 place-items-center rounded-lg bg-accent text-accent-foreground">
                            <Icon className="size-5" />
                          </span>
                          <p className="mt-3 font-heading text-base font-semibold">
                            {t(tool.titleKey)}
                          </p>
                          <p className="mt-1 text-sm text-muted-foreground">{t(tool.descKey)}</p>
                        </button>
                      );
                    })}
                  </div>

                  {active && active.category === tb.id ? (
                    <div className="mt-8">
                      <ToolPanel
                        key={active.id}
                        tool={active}
                        lang={lang}
                        onBack={() => setActiveId(null)}
                      />
                    </div>
                  ) : null}
                </TabsContent>
              );
            })}
          </Tabs>
        </section>
      </main>

      <footer className="border-t border-border py-6">
        <p className="mx-auto max-w-5xl px-5 font-mono text-xs text-muted-foreground">
          {t("footer")}
        </p>
      </footer>
    </div>
  );
}
