"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Snapshot } from "@/lib/contracts";

const PAIRS = ["SOL", "XRP", "DOGE", "LINK", "SUI", "AVAX", "ADA"];
const time = (value?: string | null) => value ? new Date(value).toLocaleString(undefined, {hour12: false}) : "No observation";
const percent = (value?: string | null) => value != null && Number.isFinite(Number(value)) ? `${Number(value) >= 0 ? "+" : ""}${(Number(value) * 100).toFixed(2)}%` : "—";
const price = (value?: string | null) => value != null && Number.isFinite(Number(value)) ? Number(value).toLocaleString(undefined, {maximumFractionDigits: 6}) : "—";
function Badge({value}: {value: string}) { return <span className={`badge ${value}`}>{value.replaceAll("_", " ")}</span>; }
function Radar() { return <svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="13"/><circle cx="16" cy="16" r="7"/><path d="M16 3v13l9-9M3 16h5m16 0h5M16 24v5"/><circle className="blip" cx="11" cy="20" r="2"/></svg>; }

export default function Dashboard() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [busy, setBusy] = useState(true);
  const [failed, setFailed] = useState(false);
  const [category, setCategory] = useState("all");
  const active = useRef<AbortController | null>(null);
  const refresh = useCallback(async () => {
    if (active.current) return;
    const controller = new AbortController(); active.current = controller; setBusy(true);
    try {
      const response = await fetch("/api/dashboard", {cache: "no-store", signal: controller.signal});
      if (!response.ok) throw new Error("unavailable");
      setSnapshot(await response.json()); setFailed(false);
    } catch { if (!controller.signal.aborted) setFailed(true); }
    finally { if (!controller.signal.aborted) setBusy(false); if (active.current === controller) active.current = null; }
  }, []);
  useEffect(() => { void refresh(); const timer = setInterval(() => void refresh(), 30000);
    return () => {clearInterval(timer); active.current?.abort(); active.current = null;}; }, [refresh]);

  const markets = snapshot?.core.data?.markets;
  const btc = snapshot?.btc.data;
  const collector = snapshot?.collector.data;
  const allScans = snapshot?.scans.data?.scans || [];
  const scans = allScans.filter(scan => category === "all" || scan.categories.includes(category));
  const current = markets?.filter(m => m.status === "current").length || 0;
  const sourceLabel = !snapshot ? "Waiting for observations" : snapshot.core.status === "unavailable" ? "Core feed unavailable" : snapshot.core.data.data_status === "storage_disabled" ? "Storage not configured" : "Stored observations";
  return <div className="shell">
    <a className="skip" href="#main">Skip to content</a>
    <aside className="sidebar">
      <a className="brand" href="#main"><Radar/><span>MOCHEX<span className="brand-sub">RADAR</span></span></a>
      <div className="workspace">RESEARCH WORKSPACE</div>
      <nav aria-label="Main navigation"><a href="#core"><span>◈</span> Core markets <b>07</b></a><a href="#context"><span>◎</span> BTC context</a><a href="#dex"><span>⌁</span> DEX radar</a><a href="#system"><span>▤</span> System health</a></nav>
      <div className="sidebar-bottom"><span className="mode-dot"/> Research mode<p>Observations & evidence<br/>MEXC USDT futures · Solana</p></div>
    </aside>
    <main id="main">
      <header className="topbar"><span>WORKSPACE <span className="slash">/</span> Market overview</span><span className="read-only">READ ONLY</span></header>
      <section className="page-heading"><div><div className="eyebrow">YOUR MARKET WORKSPACE</div><h1>Market overview<span className="title-dot">.</span></h1><p>Seven core pairs. Broader context. Evidence before action.</p></div><button onClick={() => void refresh()} disabled={busy}>{busy ? "Refreshing…" : "↻ Refresh data"}</button></section>
      <div className="feedline" role="status"><span className={`dot ${current ? "green" : ""}`}/>{sourceLabel}<span className="divider">·</span><span>Refreshes every 30 seconds</span><span className="last-update">Last checked {snapshot ? time(snapshot.fetched_at) : "—"}</span></div>
      {failed && <div className="notice" role="alert">Refresh failed. {snapshot ? "Showing the last successful snapshot; observations may be outdated." : "The dashboard cannot reach its data service. Try refreshing."}</div>}
      <div className="summary-grid">
        <article className="summary"><span className="label">CORE COVERAGE</span><div className="big-number">{current}<small> / 7</small></div><p>Pairs with a current 15m observation</p></article>
        <article className="summary"><span className="label">BTC MARKET CONTEXT</span><div className="summary-value">{btc ? <Badge value={btc.state}/> : "Unavailable"}</div><p>Provisional context · {btc?.rule_version || "Awaiting evidence"}</p></article>
        <article className="summary"><span className="label">DEX SCAN HISTORY</span><div className="big-number">{snapshot?.scans.status === "available" ? allScans.length : "—"}<small> records</small></div><p>Most recent recorded scans · up to 100</p></article>
      </div>
      <section className="panel" id="core"><div className="panel-heading"><div><h2>Core markets</h2><p>MEXC USDT futures <span className="tiny-separator">/</span> Last closed 15m candle</p></div><span className="tag">7 PAIRS</span></div>
        <div className="table-wrap"><table><thead><tr><th>Market</th><th>Close · USDT</th><th>15m return</th><th>Observation</th><th>Candle closed at</th></tr></thead><tbody>
          {PAIRS.map((base, i) => {const market = markets?.find(m => m.base === base); return <tr key={base}><td><div className="asset"><span className={`coin coin-${i}`}>{base.slice(0, 1)}</span><strong>{base}<span className="quote"> / USDT</span></strong></div></td><td className="numeric">{price(market?.close)}</td><td className={`numeric ${market?.candle_return && Number(market.candle_return) < 0 ? "negative" : ""}`}>{percent(market?.candle_return)}</td><td><Badge value={failed ? "outdated" : market?.status || "missing"}/></td><td className="muted time">{time(market?.close_time)}</td></tr>;})}
        </tbody></table></div><div className="panel-foot">Prices are stored candle closes. Missing observations display as —. Stale values retain their timestamp.</div>
      </section>
      <div className="detail-grid">
        <section className="panel" id="context"><div className="panel-heading"><div><h2>BTC context</h2><p>Broad market conditions</p></div><span className="tag">PROVISIONAL</span></div><div className="panel-body"><div className="context-row"><span>Current regime</span><Badge value={btc?.state || "unavailable"}/></div><div className="context-row"><span>1h observed return</span><strong className="numeric">{percent(btc?.return_1h)}</strong></div><div className="context-row"><span>Evidence candles</span><strong>{btc?.input_open_times.length ?? 0} / 4</strong></div><div className="context-row"><span>Data as of</span><span className="time">{time(btc?.data_as_of)}</span></div><p className="context-note">{btc?.reason === "insufficient_data" ? "Waiting for four consecutive BTC candles." : btc?.reason.replaceAll("_", " ") || "BTC context is currently unavailable."} This screening rule is provisional.</p></div></section>
        <section className="panel" id="system"><div className="panel-heading"><div><h2>Collection health</h2><p>Latest completed collection cycle</p></div><span className="tag">SYSTEM</span></div><div className="panel-body"><div className="context-row"><span>Collector</span><Badge value={collector?.status || "unavailable"}/></div><div className="context-row"><span>Candles stored</span><strong>{collector?.last_cycle?.stored_count ?? "—"}</strong></div><div className="context-row"><span>Provider failures</span><strong>{collector?.last_cycle?.provider_failures ?? "—"}</strong></div><div className="context-row"><span>Last completed</span><span className="time">{time(collector?.last_cycle?.finished_at)}</span></div><p className="context-note">A completed collection cycle describes the last run. It does not confirm that a worker is running now.</p></div></section>
      </div>
      <section className="panel" id="dex"><div className="panel-heading"><div><h2>DEX radar</h2><p>Configured Solana mints · Scan evidence</p></div><div className="filters" role="group" aria-label="DEX category">{["all", "meme", "ai"].map(item => <button key={item} aria-pressed={category === item} onClick={() => setCategory(item)}>{item === "ai" ? "AI" : item === "all" ? "All scans" : "Meme"}</button>)}</div></div>
        {scans.length ? <div className="table-wrap"><table><thead><tr><th>Solana mint</th><th>Category</th><th>Outcome</th><th>Pools</th><th>Completed at</th></tr></thead><tbody>{scans.map(scan => <tr key={scan.id}><td><span className="mint" title={scan.mint}>{scan.mint}</span><small className="provenance">{scan.category_source}</small></td><td>{scan.categories.join(" · ")}</td><td><Badge value={scan.status}/></td><td className="numeric">{scan.pool_count}</td><td className="muted time">{time(scan.finished_at)}</td></tr>)}</tbody></table></div> : <div className="empty"><span className="empty-icon">⌁</span><h3>{snapshot?.scans.status === "unavailable" ? "Scan history unavailable" : "No recorded scans"}</h3><p>{category === "all" ? "Scans will appear here once a configured watchlist has been scanned." : `No recorded scans tagged ${category === "ai" ? "AI" : "Meme"}.`}</p></div>}
        <div className="panel-foot">Categories come from the configured watchlist. Security checks and Pump / Dump signal evaluation are not yet available.</div>
      </section>
      <footer><span>MOCHEX RADAR <span className="slash">/</span> Research workspace</span><span>Public market observations · No trade execution</span></footer>
    </main>
  </div>;
}
