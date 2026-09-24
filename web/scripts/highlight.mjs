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

const render = (tokens) =>
  tokens.map((t) => `<span style="color:${t.color}">${esc(t.content)}</span>`).join("");

export async function highlightDiff(diff, highlighter) {
  const lines = parseDiff(diff);
  const byFile = new Map();
  lines.forEach((l, i) => {
    if (l.kind === "file" || l.kind === "hunk") return;
    if (!byFile.has(l.file)) byFile.set(l.file, []);
    byFile.get(l.file).push(i);
  });
  for (const [file, idxs] of byFile) {
    const lang = file.endsWith(".py") ? "python" : "text";
    // Each side is tokenised as one block, so multi-line strings stay right.
    for (const side of ["new", "old"]) {
      const sideIdx = idxs.filter((i) => (side === "new" ? lines[i].kind !== "del" : lines[i].kind !== "add"));
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
