import { candidateEvaluationSchema } from "@/lib/contracts";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const mint = searchParams.get("mint");
  if (!mint || !/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(mint)) {
    return Response.json(
      { status: "invalid_mint", data: null },
      { status: 400 },
    );
  }
  const origin = process.env.RADAR_API_ORIGIN || "http://127.0.0.1:8000";
  try {
    const response = await fetch(
      new URL(`/api/v1/candidates/solana/${mint}/evaluation`, origin),
      {
        headers: process.env.RADAR_API_TOKEN
          ? { Authorization: `Bearer ${process.env.RADAR_API_TOKEN}` }
          : {},
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      },
    );
    if (!response.ok) throw new Error("upstream error");
    const json = await response.json();
    return Response.json({
      status: "available",
      data: candidateEvaluationSchema.parse(json),
    });
  } catch {
    return Response.json(
      { status: "unavailable", data: null },
      { status: 503 },
    );
  }
}
