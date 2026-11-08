import { walletHistoryOverviewSchema } from "@/lib/contracts";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const address = searchParams.get("address");
  if (!address || !/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(address)) {
    return Response.json(
      { status: "invalid_address", data: null },
      { status: 400 },
    );
  }
  const poll = searchParams.get("poll") === "true";
  const origin = process.env.RADAR_API_ORIGIN || "http://127.0.0.1:8000";
  const authHeader: Record<string, string> = process.env.RADAR_API_TOKEN
    ? { Authorization: `Bearer ${process.env.RADAR_API_TOKEN}` }
    : {};

  if (poll) {
    // Attempt best-effort on-demand wallet poll if polling is enabled upstream
    await Promise.allSettled([
      fetch(new URL(`/api/v1/security/solana/wallets/${encodeURIComponent(address)}/poll`, origin), {
        method: "POST",
        headers: authHeader,
        cache: "no-store",
        signal: AbortSignal.timeout(6000),
      }),
    ]);
  }

  try {
    const response = await fetch(
      new URL(`/api/v1/security/solana/wallets/${encodeURIComponent(address)}/history`, origin),
      {
        headers: authHeader,
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      },
    );
    if (!response.ok) throw new Error("upstream error");
    const json = await response.json();
    return Response.json({
      status: "available",
      data: walletHistoryOverviewSchema.parse(json),
    });
  } catch {
    return Response.json(
      { status: "unavailable", data: null },
      { status: 503 },
    );
  }
}
