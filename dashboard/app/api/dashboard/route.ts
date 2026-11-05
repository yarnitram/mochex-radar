import { z } from "zod";
import {
  btcSchema,
  collectorSchema,
  coreSchema,
  scansSchema,
  outboxSchema,
  catalogSchema,
  profilePollsSchema,
  Service,
} from "@/lib/contracts";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

async function read<T>(
  path: string,
  schema: z.ZodType<T>,
): Promise<Service<T>> {
  try {
    const origin = process.env.RADAR_API_ORIGIN || "http://127.0.0.1:8000";
    const response = await fetch(new URL(path, origin), {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) throw new Error("upstream unavailable");
    return { status: "available", data: schema.parse(await response.json()) };
  } catch {
    return { status: "unavailable", data: null };
  }
}

export async function GET() {
  const [core, btc, collector, scans, outbox, catalog, profilePolls] =
    await Promise.all([
      read("/api/v1/dashboard/core", coreSchema),
      read("/api/v1/market-context/btc", btcSchema),
      read("/api/v1/collector/status", collectorSchema),
      read("/api/v1/dex/scans?limit=100", scansSchema),
      read("/api/v1/alerts/status", outboxSchema),
      read("/api/v1/discovery/profiles/mints?limit=100", catalogSchema),
      read("/api/v1/discovery/profiles/polls?limit=10", profilePollsSchema),
    ]);
  return Response.json(
    {
      fetched_at: new Date().toISOString(),
      core,
      btc,
      collector,
      scans,
      outbox,
      catalog,
      profilePolls,
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}
