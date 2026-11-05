import { z } from "zod";

export const coreSchema = z.object({
  data_status: z.string(), as_of: z.string(), interval: z.literal("15m"),
  markets: z.array(z.object({asset_id: z.string(), base: z.string(), quote: z.string(), market_id: z.string(),
    status: z.enum(["current", "stale", "missing"]), close: z.string().nullable(), candle_return: z.string().nullable(),
    close_time: z.string().nullable(), retrieved_at: z.string().nullable()})),
});
export const btcSchema = z.object({state: z.enum(["unknown", "neutral", "supportive", "caution", "blocked"]),
  reason: z.string(), rule_version: z.string(), provisional: z.boolean(), return_1h: z.string().nullable(),
  data_as_of: z.string().nullable(), input_open_times: z.array(z.string())});
export const collectorSchema = z.object({status: z.string(), last_cycle: z.object({
  finished_at: z.string(), stored_count: z.number(), provider_failures: z.number(),
}).nullable()});
export const scansSchema = z.object({status: z.string(), scans: z.array(z.object({
  id: z.string(), mint: z.string(), categories: z.array(z.string()), category_source: z.string(),
  finished_at: z.string(), status: z.enum(["success", "empty", "provider_error", "budget_exhausted", "skipped_budget"]),
  pool_count: z.number(),
}))});
export type Service<T> = {status: "available"; data: T} | {status: "unavailable"; data: null};
export type Snapshot = {fetched_at: string; core: Service<z.infer<typeof coreSchema>>;
  btc: Service<z.infer<typeof btcSchema>>; collector: Service<z.infer<typeof collectorSchema>>;
  scans: Service<z.infer<typeof scansSchema>>};
