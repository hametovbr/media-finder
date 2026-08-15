import { cp, mkdir, rm } from "node:fs/promises";

const source = new URL("../assets-src/", import.meta.url);
const target = new URL(
  "../packages/builtin-ui/src/media_finder_builtin_ui/static/",
  import.meta.url,
);

await rm(target, { force: true, recursive: true });
await mkdir(target, { recursive: true });
await cp(source, target, { recursive: true });
await cp(
  new URL("../node_modules/htmx.org/dist/htmx.min.js", import.meta.url),
  new URL("./htmx.min.js", target),
);
await cp(
  new URL("../node_modules/axe-core/axe.min.js", import.meta.url),
  new URL("./axe.min.js", target),
);
