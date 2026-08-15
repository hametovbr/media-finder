import { cp, mkdir, rm } from "node:fs/promises";

const source = new URL("../assets-src/", import.meta.url);
const target = new URL("../src/media_finder/static/", import.meta.url);

await rm(target, { force: true, recursive: true });
await mkdir(target, { recursive: true });
await cp(source, target, { recursive: true });
