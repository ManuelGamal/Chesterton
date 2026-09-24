// Build step: Shiki-highlight each story's diff into <id>.lines.json (demo spec §3).
import { readFile, writeFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { createHighlighter } from "shiki";

export const THEME = "github-dark-default";

const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

export function parseDiff(diff) {
  const out = [];
  let file = null;
  let oldNo = 0;
  let newNo = 0;
  for (const raw of diff.split("\n")) {
    if (raw.startsWith("diff --git ")) {
      const m = raw.match(/ b\/(.+)$/);
      file = m ? m[1] : raw;
      out.push({ kind: "file", file, old: null, new: null, text: file });
      continue;
    }
    if (/^(--- |\+\+\+ |index |new file mode|deleted file mode|similarity |rename )/.test(raw)) continue;
    const h = raw.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if (h) {
      oldNo = Number(h[1]);
      newNo = Number(h[2]);
      out.push({ kind: "hunk", file, old: null, new: null, text: raw });
      continue;
    }
    if (file === null || raw === "" || raw.startsWith("\\")) continue;
    const tag = raw[0];
    const text = raw.slice(1);
    if (tag === "+") out.push({ kind: "add", file, old: null, new: newNo++, text });
    else if (tag === "-") out.push({ kind: "del", file, old: oldNo++, new: null, text });
    else out.push({ kind: "ctx", file, old: oldNo++, new: newNo++, text });
  }
  return out;
}

const HEX_COLOR = /^#[0-9a-fA-F]{3,8}$/;

const render = (tokens) =>
  tokens
    .map((t) => {
      const text = esc(t.content);
      return HEX_COLOR.test(t.color) ? `<span style="color:${t.color}">${text}</span>` : text;
    })
    .join("");

export async function highlightDiff(diff, highlighter) {
  const lines = parseDiff(diff);
  // Group by hunk (not by file): a hunk is tokenised independently of its
  // neighbours, so an unclosed string/docstring in one hunk's context can't
  // bleed its colour into the next hunk, which the diff never actually joins.
  const groups = [];
  let current = null;
  lines.forEach((l, i) => {
    if (l.kind === "file") {
      current = null;
      return;
    }
    if (l.kind === "hunk") {
      current = { file: l.file, idxs: [] };
      groups.push(current);
      return;
    }
    if (current) current.idxs.push(i);
  });
  for (const { file, idxs } of groups) {
    const lang = file.endsWith(".py") ? "python" : "text";
    // Each side of each hunk is tokenised as one block, so multi-line strings stay right.
    for (const side of ["new", "old"]) {
      const sideIdx = idxs.filter((i) => (side === "new" ? lines[i].kind !== "del" : lines[i].kind !== "add"));
      if (sideIdx.length === 0) continue;
      const code = sideIdx.map((i) => lines[i].text).join("\n");
      const { tokens } = highlighter.codeToTokens(code, { lang, theme: THEME });
      sideIdx.forEach((i, k) => {
        if (side === "new" || lines[i].kind === "del") lines[i].html = render(tokens[k] ?? []);
      });
    }
  }
  return lines.map((l) => ({ kind: l.kind, file: l.file, old: l.old, new: l.new, html: l.html ?? esc(l.text) }));
}

async function main() {
  const dir = new URL("../public/stories/", import.meta.url);
  const index = JSON.parse(await readFile(new URL("index.json", dir), "utf8"));
  const hl = await createHighlighter({ themes: [THEME], langs: ["python"] });
  for (const { id } of index.stories) {
    const bundle = JSON.parse(await readFile(new URL(`${id}.json`, dir), "utf8"));
    const lines = await highlightDiff(bundle.patch.diff, hl);
    await writeFile(new URL(`${id}.lines.json`, dir), JSON.stringify(lines));
    console.log(`highlighted ${id}: ${lines.length} lines`);
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  await main();
}
