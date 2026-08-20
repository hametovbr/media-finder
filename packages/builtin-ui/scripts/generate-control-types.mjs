import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const schema = path.resolve(packageRoot, "../../docs/api/control-v1.openapi.json");
const output = path.resolve(packageRoot, "web/src/api/control.generated.ts");
const temporary = path.join(os.tmpdir(), `media-finder-control-${process.pid}.ts`);
const digest = crypto.createHash("sha256").update(fs.readFileSync(schema)).digest("hex");

try {
  const generated = spawnSync(
    "pnpm",
    ["exec", "openapi-typescript", schema, "--output", temporary],
    { cwd: packageRoot, encoding: "utf8" },
  );
  if (generated.status !== 0) {
    process.stderr.write(generated.stderr || generated.stdout);
    process.exit(generated.status ?? 1);
  }

  const expected = `// OpenAPI SHA256: ${digest}\n${fs.readFileSync(temporary, "utf8")}`;
  if (process.argv.includes("--check")) {
    const actual = fs.existsSync(output) ? fs.readFileSync(output, "utf8") : "";
    if (actual !== expected) {
      process.stderr.write("Generated control types are stale; run pnpm contract:generate.\n");
      process.exit(1);
    }
  } else {
    fs.mkdirSync(path.dirname(output), { recursive: true });
    fs.writeFileSync(output, expected, "utf8");
  }
} finally {
  fs.rmSync(temporary, { force: true });
}
