import { cp, mkdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const output = path.join(here, "dist");
await mkdir(output, { recursive: true });
await cp(path.join(here, "index.html"), path.join(output, "index.html"));
await cp(path.join(here, "static"), path.join(output, "static"), { recursive: true });

const apiBase = (process.env.RECSYS_API_BASE_URL || "").replace(/\/$/, "");
await writeFile(
  path.join(output, "config.js"),
  `window.RECSYS_API_BASE_URL = ${JSON.stringify(apiBase)};\n`,
  "utf8",
);

console.log(`Built Vercel static output at ${output}`);
