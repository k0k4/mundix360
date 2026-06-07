import { useEffect, useRef, useState } from "react";

const STORAGE_KEY = "mundix-sider-width";
const MIN_WIDTH = 180;
const MAX_WIDTH = 460;
const DEFAULT_WIDTH = 240;

function clamp(w: number): number {
  return Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, w));
}

function isCollapsed(): boolean {
  const sider = document.querySelector(".ant-layout-sider");
  return !!sider && sider.classList.contains("ant-layout-sider-collapsed");
}

/**
 * Refine's fixed ThemedSiderV2 hardcodes its width (200px) inline on three
 * elements: the flow spacer (reserves content offset), the <aside> itself, and
 * the brand/title wrapper. The CSS variable drives the <aside> and the drag
 * handle; this helper imperatively syncs the two inline-styled <div>s so the
 * page content and the brand area follow the new width. No-ops while collapsed
 * (Refine owns the 80px collapsed width).
 */
function applyWidth(w: number): void {
  document.documentElement.style.setProperty("--mx-sider-width", `${w}px`);
  if (isCollapsed()) return;

  const px = `${w}px`;

  // Flow spacer: the <div> Refine renders immediately before the fixed <aside>
  // to reserve horizontal space (this is what offsets the page content). Pin
  // every sizing axis so it cannot flex-shrink and let content overlap.
  const sider = document.querySelector(".ant-layout-sider");
  const spacer = sider?.previousElementSibling as HTMLElement | null;
  if (spacer && spacer.tagName === "DIV") {
    spacer.style.width = px;
    spacer.style.minWidth = px;
    spacer.style.maxWidth = px;
    spacer.style.flex = `0 0 ${px}`;
  }

  // Brand/title wrapper: first <div> inside the sider body.
  const brand = document.querySelector<HTMLElement>(
    ".ant-layout-sider-children > div"
  );
  if (brand) brand.style.width = px;
}

/**
 * Draggable handle that lets the operator resize the lateral menu by dragging
 * its right edge. The chosen width is persisted (localStorage) and re-applied
 * whenever the sider expands. Hidden while collapsed or on small screens.
 */
export function SiderResizer() {
  const [collapsed, setCollapsed] = useState(false);
  const widthRef = useRef<number>(DEFAULT_WIDTH);
  const cleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    const saved = parseInt(localStorage.getItem(STORAGE_KEY) || "", 10);
    widthRef.current = Number.isFinite(saved) ? clamp(saved) : DEFAULT_WIDTH;
    applyWidth(widthRef.current);
  }, []);

  // Watch the sider's collapsed state; re-apply our width whenever it expands
  // (Refine resets the inline widths back to 200px on expand). Retries until the
  // sider exists in case the layout mounts asynchronously.
  useEffect(() => {
    let classObs: MutationObserver | null = null;
    let bodyObs: MutationObserver | null = null;

    const attach = (sider: Element) => {
      const sync = () => {
        const c = sider.classList.contains("ant-layout-sider-collapsed");
        setCollapsed(c);
        if (!c) requestAnimationFrame(() => applyWidth(widthRef.current));
      };
      sync();
      classObs = new MutationObserver(sync);
      classObs.observe(sider, { attributes: true, attributeFilter: ["class"] });
    };

    const found = document.querySelector(".ant-layout-sider");
    if (found) {
      attach(found);
    } else {
      bodyObs = new MutationObserver(() => {
        const s = document.querySelector(".ant-layout-sider");
        if (s) {
          bodyObs?.disconnect();
          bodyObs = null;
          attach(s);
        }
      });
      bodyObs.observe(document.body, { childList: true, subtree: true });
    }

    return () => {
      classObs?.disconnect();
      bodyObs?.disconnect();
    };
  }, []);

  // Ensure any in-flight drag is torn down if the component unmounts.
  useEffect(() => () => cleanupRef.current?.(), []);

  const beginDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    const onMove = (ev: PointerEvent) => {
      const w = clamp(ev.clientX);
      widthRef.current = w;
      applyWidth(w);
    };
    const finish = () => {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      localStorage.setItem(STORAGE_KEY, String(widthRef.current));
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", finish);
      window.removeEventListener("pointercancel", finish);
      window.removeEventListener("blur", finish);
      cleanupRef.current = null;
    };

    cleanupRef.current = finish;
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", finish);
    window.addEventListener("pointercancel", finish);
    window.addEventListener("blur", finish);
  };

  const resetWidth = () => {
    widthRef.current = DEFAULT_WIDTH;
    applyWidth(DEFAULT_WIDTH);
    localStorage.setItem(STORAGE_KEY, String(DEFAULT_WIDTH));
  };

  if (collapsed) return null;

  return (
    <div
      className="mx-sider-resizer"
      role="separator"
      aria-orientation="vertical"
      aria-label="Redimensionar menu lateral"
      title="Arraste para redimensionar • duplo clique para restaurar"
      onPointerDown={beginDrag}
      onDoubleClick={resetWidth}
    />
  );
}
