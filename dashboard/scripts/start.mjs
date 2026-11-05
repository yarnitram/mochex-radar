import { cp } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

// Local production preview; Docker supplies its own container hostname.
process.env.HOSTNAME = "127.0.0.1";
const portFlag = process.argv.indexOf("--port");
process.env.PORT =
  portFlag >= 0 ? process.argv[portFlag + 1] : process.env.PORT || "3000";
if (!/^\d+$/.test(process.env.PORT || ""))
  throw new Error("numeric port required");
await cp(resolve(".next/static"), resolve(".next/standalone/.next/static"), {
  recursive: true,
});
await import(pathToFileURL(resolve(".next/standalone/server.js")).href);
