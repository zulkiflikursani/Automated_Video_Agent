import { useEffect, useState } from "react";

const NAV = ["Overview", "Discover", "Progress", "Sources", "Queue", "Clips", "Logs", "Settings"];

export default function Home() {
  const [tab, setTab] = useState("Overview");
  const [health, setHealth] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [sources, setSources] = useState([]);
  const [queue, setQueue] = useState([]);
  const [clips, setClips] = useState([]);
  const [logs, setLogs] = useState([]);
  const [settings, setSettings] = useState([]);
  const [videos, setVideos] = useState([]);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ name: "", url: "", platform: "youtube", check_interval_hours: 6 });
  const [notice, setNotice] = useState("");
  const [keywordGroups, setKeywordGroups] = useState({});
  const [discoverKeyword, setDiscoverKeyword] = useState("drama cina sub indo 10");
  const [discoverLimit, setDiscoverLimit] = useState(10);
  const [discoverResults, setDiscoverResults] = useState(null);
  const [discoverBusy, setDiscoverBusy] = useState(false);
  const [progressEvents, setProgressEvents] = useState([]);

  const refreshAll = async () => {
    const [h, m, s, q, c, l, st, v, k] = await Promise.all([
      fetch("/api/health").then((r) => r.json()).catch(() => null),
      fetch("/api/metrics").then((r) => r.json()).catch(() => null),
      fetch("/api/sources").then((r) => r.json()).catch(() => []),
      fetch("/api/queue").then((r) => r.json()).catch(() => []),
      fetch("/api/clips").then((r) => r.json()).catch(() => []),
      fetch("/api/logs").then((r) => r.json()).catch(() => []),
      fetch("/api/settings").then((r) => r.json()).catch(() => []),
      fetch("/api/videos").then((r) => r.json()).catch(() => []),
      fetch("/api/keywords").then((r) => r.json()).catch(() => ({})),
    ]);
    setHealth(h);
    setMetrics(m);
    setSources(Array.isArray(s) ? s : []);
    setQueue(Array.isArray(q) ? q : []);
    setClips(Array.isArray(c) ? c : []);
    setLogs(Array.isArray(l) ? l : []);
    setSettings(Array.isArray(st) ? st : []);
    setVideos(Array.isArray(v) ? v : []);
    setKeywordGroups(k?.groups || {});
  };

  const refreshProgress = async () => {
    const p = await fetch("/api/progress").then((r) => r.json()).catch(() => []);
    setProgressEvents(Array.isArray(p) ? p : []);
  };

  useEffect(() => {
    refreshAll();
    refreshProgress();
    const t = setInterval(refreshAll, 15000);
    const tp = setInterval(refreshProgress, 3000);  // live pipeline progress
    return () => { clearInterval(t); clearInterval(tp); };
  }, []);

  const flash = (msg) => {
    setNotice(msg);
    setTimeout(() => setNotice(""), 3000);
  };

  const addSource = async (e) => {
    e.preventDefault();
    setBusy(true);
    const res = await fetch("/api/sources", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    setBusy(false);
    if (res.ok) {
      setForm({ name: "", url: "", platform: "youtube", check_interval_hours: 6 });
      flash("Source added");
      refreshAll();
    } else {
      const err = await res.json().catch(() => ({}));
      flash(err.detail || "Failed to add source");
    }
  };

  const toggleSource = async (s) => {
    await fetch(`/api/sources/${s.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: !s.is_active }),
    });
    refreshAll();
  };

  const deleteSource = async (id) => {
    await fetch(`/api/sources/${id}`, { method: "DELETE" });
    flash("Source deleted");
    refreshAll();
  };

  const publishNow = async (entry) => {
    setBusy(true);
    const res = await fetch(`/api/queue/${entry.id}/publish-now`, { method: "POST" });
    setBusy(false);
    flash(res.ok ? "Publish cycle executed" : "Publish failed");
    refreshAll();
  };

  const reschedule = async (entry, hours) => {
    const when = new Date(Date.now() + hours * 3600 * 1000).toISOString();
    await fetch(`/api/queue/${entry.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scheduled_for: when }),
    });
    flash(hours >= 0 ? `Delayed ${hours}h` : `Moved earlier ${-hours}h`);
    refreshAll();
  };

  const deleteEntry = async (id) => {
    await fetch(`/api/queue/${id}`, { method: "DELETE" });
    flash("Queue entry deleted");
    refreshAll();
  };

  const runCycle = async () => {
    setBusy(true);
    await fetch("/api/run-cycle", { method: "POST" });
    setBusy(false);
    flash("Full cycle started in background");
    setTimeout(refreshAll, 2000);
  };

  const cleanup = async () => {
    const res = await fetch("/api/cleanup", { method: "POST" }).then((r) => r.json());
    flash(`GC removed ${res.files_removed} file(s)`);
    refreshAll();
  };

  const updateSetting = async (key, value) => {
    await fetch(`/api/settings/${key}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value }),
    });
    flash(`Setting ${key} updated`);
    refreshAll();
  };

  const searchDiscover = async (e) => {
    e && e.preventDefault();
    setDiscoverBusy(true);
    const res = await fetch("/api/discover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keyword: discoverKeyword, limit: discoverLimit }),
    });
    setDiscoverBusy(false);
    if (res.ok) {
      const body = await res.json();
      setDiscoverResults(body.results);
      flash(`Ditemukan ${body.count} video untuk "${body.keyword}"`);
    } else {
      const err = await res.json().catch(() => ({}));
      flash(err.detail || "Search gagal");
      setDiscoverResults([]);
    }
  };

  const addToPipeline = async (r) => {
    const res = await fetch("/api/discover/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_id: r.id, title: r.title, url: r.url, duration: r.duration }),
    });
    if (res.status === 409) {
      flash("Video sudah ada di pipeline");
    } else if (res.ok) {
      flash(`"${r.title.slice(0, 40)}..." masuk antrean proses`);
      setDiscoverResults((rs) => (rs || []).filter((x) => x.id !== r.id));
      refreshAll();
    } else {
      flash("Gagal menambahkan video");
    }
  };

  const applyTemplate = (tmpl) => {
    setDiscoverKeyword(tmpl.replace("{n}", String(discoverLimit)));
  };

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      {/* Header */}
      <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600 text-lg font-bold text-white">FV</div>
          <div>
            <h1 className="text-xl font-bold text-white">FB Video Auto-Agent</h1>
            <p className="text-xs text-slate-400">Automated Video Syndication Agent</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={`badge ${health?.dry_run ? "bg-amber-500/20 text-amber-300" : "bg-emerald-500/20 text-emerald-300"}`}>
            {health?.dry_run ? "DRY-RUN MODE" : "LIVE MODE"}
          </span>
          <span className={`badge ${health?.ok ? "bg-emerald-500/20 text-emerald-300" : "bg-red-500/20 text-red-300"}`}>
            {health?.ok ? "ACTIVE" : "OFFLINE"}
          </span>
          <button className="btn-primary" onClick={runCycle} disabled={busy}>Run Cron Now</button>
          <button className="btn-ghost" onClick={cleanup}>Cleanup</button>
        </div>
      </header>

      {notice && (
        <div className="mb-4 rounded-lg border border-indigo-800 bg-indigo-950/60 px-4 py-2 text-sm text-indigo-200">
          {notice}
        </div>
      )}

      <div className="flex flex-col gap-6 lg:flex-row">
        {/* Navigation */}
        <nav className="flex w-full shrink-0 flex-row gap-1 overflow-x-auto lg:w-48 lg:flex-col">
          {NAV.map((item) => (
            <button
              key={item}
              onClick={() => setTab(item)}
              className={`rounded-lg px-3 py-2 text-left text-sm font-medium transition ${
                tab === item ? "bg-indigo-600/20 text-indigo-300" : "text-slate-400 hover:bg-slate-900"
              }`}
            >
              {item}
            </button>
          ))}
        </nav>

        {/* Main panel */}
        <main className="min-w-0 flex-1 space-y-6">
          {tab === "Overview" && (
            <>
              <section className="grid grid-cols-2 gap-4 md:grid-cols-4">
                <Metric label="Total Videos" value={metrics?.total_videos ?? "–"} />
                <Metric label="Reels Cut" value={metrics?.reels_cut ?? "–"} />
                <Metric label="Success Rate" value={metrics?.success_rate != null ? `${metrics.success_rate}%` : "–"} />
                <Metric label="Queued" value={metrics?.queued ?? "–"} />
              </section>

              <section className="card">
                <h2 className="mb-3 font-semibold text-white">Live Pipeline Progress</h2>
                <ProgressFeed events={progressEvents.slice(0, 6)} />
              </section>

              <QueueTable
                queue={queue.slice(0, 6)}
                onPublishNow={publishNow}
                onReschedule={reschedule}
                onDelete={deleteEntry}
                busy={busy}
              />

              <section className="card">
                <h2 className="mb-3 font-semibold text-white">Recent Logs & Alerts</h2>
                <div className="space-y-1 font-mono text-xs">
                  {logs.slice(0, 8).map((log, i) => (
                    <div key={i} className="flex gap-2">
                      <span className="text-slate-500">[{(log.at || "").replace("T", " ").slice(0, 19)}]</span>
                      <span className={
                        log.level === "SUCCESS" ? "text-emerald-400" :
                        log.level === "WARN" ? "text-amber-400" : "text-red-400"
                      }>[{log.level}]</span>
                      <span className="truncate text-slate-300">{log.message}</span>
                    </div>
                  ))}
                  {logs.length === 0 && <p className="text-slate-500">No activity yet.</p>}
                </div>
              </section>
            </>
          )}

          {tab === "Discover" && (
            <>
              <section className="card">
                <h2 className="mb-3 font-semibold text-white">Cari Video Trending (YouTube)</h2>
                <form onSubmit={searchDiscover} className="flex flex-wrap gap-2">
                  <input className="input flex-1 min-w-[16rem]"
                         placeholder="Kata kunci, mis. drama cina CEO sub indo"
                         value={discoverKeyword}
                         onChange={(e) => setDiscoverKeyword(e.target.value)} />
                  <select className="input w-24" value={discoverLimit}
                          onChange={(e) => setDiscoverLimit(Number(e.target.value))}>
                    {[5, 10, 15, 20, 30].map((n) => (
                      <option key={n} value={n}>{n} video</option>
                    ))}
                  </select>
                  <button className="btn-primary" disabled={discoverBusy}>
                    {discoverBusy ? "Mencari…" : "Search"}
                  </button>
                </form>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <span className="text-xs text-slate-500">Template:</span>
                  {Object.entries(keywordGroups).map(([group, tmpls]) => (
                    <div key={group} className="flex flex-wrap gap-1">
                      {tmpls.map((tmpl) => (
                        <button key={tmpl} type="button" onClick={() => applyTemplate(tmpl)}
                                title={group}
                                className="badge bg-slate-800 text-slate-300 hover:bg-indigo-900 hover:text-indigo-200">
                          {tmpl}
                        </button>
                      ))}
                    </div>
                  ))}
                </div>
              </section>

              {discoverResults && (
                <section className="card overflow-x-auto">
                  <h2 className="mb-3 font-semibold text-white">
                    Hasil ({discoverResults.length}) — klik Add untuk masuk pipeline
                  </h2>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-slate-400">
                        <th className="pb-2">Title</th><th className="pb-2">Channel</th>
                        <th className="pb-2">Duration</th><th className="pb-2">Views</th><th className="pb-2"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {discoverResults.map((r) => (
                        <tr key={r.id} className="border-t border-slate-800">
                          <td className="max-w-md truncate py-2 font-medium text-slate-200">
                            <a href={r.url} target="_blank" rel="noreferrer" className="hover:text-indigo-300">{r.title}</a>
                          </td>
                          <td className="py-2 text-slate-400">{r.channel}</td>
                          <td className="py-2 text-slate-400">
                            {r.duration ? `${Math.floor(r.duration / 60)}m ${r.duration % 60}s` : "–"}
                          </td>
                          <td className="py-2 text-slate-400">{r.views?.toLocaleString("id-ID")}</td>
                          <td className="py-2 text-right">
                            <button className="btn-primary" onClick={() => addToPipeline(r)}>+ Add</button>
                          </td>
                        </tr>
                      ))}
                      {discoverResults.length === 0 && (
                        <tr><td colSpan="5" className="py-6 text-center text-slate-500">Tidak ada hasil.</td></tr>
                      )}
                    </tbody>
                  </table>
                </section>
              )}
            </>
          )}

          {tab === "Progress" && (
            <section className="card">
              <h2 className="mb-3 font-semibold text-white">
                Pipeline Progress <span className="text-xs font-normal text-emerald-400">(live, refresh 3s)</span>
              </h2>
              <ProgressFeed events={progressEvents} />
            </section>
          )}

          {tab === "Sources" && (
            <>
              <section className="card">
                <h2 className="mb-3 font-semibold text-white">Add Source (YouTube / TikTok / Douyin)</h2>
                <form onSubmit={addSource} className="grid gap-2 md:grid-cols-[1fr_2fr_auto_auto_auto]">
                  <input className="input" placeholder="Name" value={form.name}
                         onChange={(e) => setForm({ ...form, name: e.target.value })} required />
                  <input className="input" placeholder="Playlist / channel URL" value={form.url}
                         onChange={(e) => setForm({ ...form, url: e.target.value })} required />
                  <select className="input" value={form.platform}
                          onChange={(e) => setForm({ ...form, platform: e.target.value })}>
                    <option value="youtube">youtube</option>
                    <option value="tiktok">tiktok</option>
                    <option value="douyin">douyin</option>
                  </select>
                  <input className="input w-20" type="number" min="1" value={form.check_interval_hours}
                         onChange={(e) => setForm({ ...form, check_interval_hours: Number(e.target.value) })} />
                  <button className="btn-primary" disabled={busy}>Add</button>
                </form>
              </section>

              <section className="card overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-slate-400">
                      <th className="pb-2">ID</th><th className="pb-2">Name</th><th className="pb-2">URL</th>
                      <th className="pb-2">Interval</th><th className="pb-2">Videos</th><th className="pb-2">Active</th><th className="pb-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {sources.map((s) => (
                      <tr key={s.id} className="border-t border-slate-800">
                        <td className="py-2 text-slate-500">{s.id}</td>
                        <td className="py-2 font-medium text-slate-200">{s.name}</td>
                        <td className="max-w-xs truncate py-2 text-slate-400">{s.url}</td>
                        <td className="py-2">{s.check_interval_hours}h</td>
                        <td className="py-2">{s.video_count}</td>
                        <td className="py-2">
                          <button onClick={() => toggleSource(s)}
                            className={`badge ${s.is_active ? "bg-emerald-500/20 text-emerald-300" : "bg-slate-700 text-slate-400"}`}>
                            {s.is_active ? "ACTIVE" : "PAUSED"}
                          </button>
                        </td>
                        <td className="py-2 text-right">
                          <button className="btn-danger" onClick={() => deleteSource(s.id)}>Delete</button>
                        </td>
                      </tr>
                    ))}
                    {sources.length === 0 && (
                      <tr><td colSpan="7" className="py-6 text-center text-slate-500">No sources yet.</td></tr>
                    )}
                  </tbody>
                </table>
              </section>
            </>
          )}

          {tab === "Queue" && (
            <QueueTable queue={queue} full onPublishNow={publishNow} onReschedule={reschedule}
                        onDelete={deleteEntry} busy={busy} />
          )}

          {tab === "Clips" && (
            <section className="card overflow-x-auto">
              <h2 className="mb-3 font-semibold text-white">Reels Clips</h2>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-400">
                    <th className="pb-2">Video</th><th className="pb-2">Part</th><th className="pb-2">Window</th>
                    <th className="pb-2">Duration</th><th className="pb-2">Overlay</th><th className="pb-2">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {clips.map((c) => (
                    <tr key={c.id} className="border-t border-slate-800">
                      <td className="max-w-xs truncate py-2 text-slate-300">{c.video_title}</td>
                      <td className="py-2">#{c.part_number}</td>
                      <td className="py-2 text-slate-400">{c.start_time_sec}s – {c.end_time_sec}s</td>
                      <td className="py-2">{c.duration}s</td>
                      <td className="max-w-xs truncate py-2 text-slate-400">{c.overlay_title}</td>
                      <td className="py-2"><StatusBadge status={c.status} /></td>
                    </tr>
                  ))}
                  {clips.length === 0 && (
                    <tr><td colSpan="6" className="py-6 text-center text-slate-500">No clips yet.</td></tr>
                  )}
                </tbody>
              </table>
            </section>
          )}

          {tab === "Logs" && (
            <section className="card">
              <h2 className="mb-3 font-semibold text-white">Logs & Telegram Alerts</h2>
              <div className="space-y-1 font-mono text-xs">
                {logs.map((log, i) => (
                  <div key={i} className="flex gap-2">
                    <span className="text-slate-500">[{(log.at || "").replace("T", " ").slice(0, 19)}]</span>
                    <span className={
                      log.level === "SUCCESS" ? "text-emerald-400" :
                      log.level === "WARN" ? "text-amber-400" : "text-red-400"
                    }>[{log.level}]</span>
                    <span className="text-slate-300">{log.message}</span>
                  </div>
                ))}
                {logs.length === 0 && <p className="text-slate-500">No activity yet.</p>}
              </div>
            </section>
          )}

          {tab === "Settings" && (
            <section className="card">
              <h2 className="mb-3 font-semibold text-white">System Settings</h2>
              <div className="space-y-3">
                {settings.map((s) => (
                  <div key={s.key} className="flex flex-wrap items-center gap-2">
                    <div className="w-56">
                      <p className="font-mono text-sm text-slate-200">{s.key}</p>
                      {s.description && <p className="text-xs text-slate-500">{s.description}</p>}
                    </div>
                    <SettingInput setting={s} onSave={updateSetting} />
                  </div>
                ))}
                {settings.length === 0 && <p className="text-slate-500">Loading…</p>}
              </div>
              <p className="mt-4 text-xs text-slate-500">
                Video statuses: {videos.map((v) => v.status).filter((s, i, a) => a.indexOf(s) === i).join(", ") || "–"}
              </p>
            </section>
          )}
        </main>
      </div>
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="card">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-bold text-white">{value}</p>
    </div>
  );
}

function ProgressFeed({ events }) {
  if (!events.length) return <p className="text-sm text-slate-500">Belum ada aktivitas pipeline.</p>;
  return (
    <div className="space-y-2">
      {events.map((ev) => (
        <div key={ev.id} className="flex items-center gap-3">
          <span className={`w-20 shrink-0 badge ${
            ev.stage === "publish" ? "bg-emerald-500/20 text-emerald-300" :
            ev.stage === "upload" ? "bg-fuchsia-500/20 text-fuchsia-300" :
            ev.stage === "process" ? "bg-amber-500/20 text-amber-300" :
            "bg-sky-500/20 text-sky-300"
          }`}>{ev.stage}</span>
          <span className="w-56 shrink-0 truncate text-sm text-slate-300">{ev.title || ev.video_ref}</span>
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-800">
            <div className={`h-full rounded-full ${ev.percent === 100 ? "bg-emerald-500" : "bg-indigo-500"}`}
                 style={{ width: `${ev.percent ?? 0}%` }} />
          </div>
          <span className="w-10 shrink-0 text-right text-xs text-slate-400">{ev.percent ?? "–"}%</span>
          <span className="w-40 shrink-0 truncate text-xs text-slate-500">{ev.detail}</span>
        </div>
      ))}
    </div>
  );
}

function StatusBadge({ status }) {
  const map = {
    SUCCESS: "bg-emerald-500/20 text-emerald-300",
    PUBLISHED: "bg-emerald-500/20 text-emerald-300",
    READY: "bg-sky-500/20 text-sky-300",
    QUEUED: "bg-indigo-500/20 text-indigo-300",
    PROCESSING: "bg-amber-500/20 text-amber-300",
    UPLOADING: "bg-amber-500/20 text-amber-300",
    PENDING: "bg-slate-700 text-slate-400",
    FAILED: "bg-red-500/20 text-red-300",
  };
  return <span className={`badge ${map[status] || "bg-slate-700 text-slate-400"}`}>{status}</span>;
}

function QueueTable({ queue, full, onPublishNow, onReschedule, onDelete, busy }) {
  return (
    <section className="card overflow-x-auto">
      <h2 className="mb-3 font-semibold text-white">
        Publishing Queue {full ? "" : "(next 6 — drip feed schedule)"}
      </h2>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-slate-400">
            <th className="pb-2">ID</th><th className="pb-2">Title</th><th className="pb-2">Type</th>
            <th className="pb-2">Scheduled For</th><th className="pb-2">Status</th><th className="pb-2">Actions</th>
          </tr>
        </thead>
        <tbody>
          {queue.map((q) => (
            <tr key={q.id} className="border-t border-slate-800">
              <td className="py-2 text-slate-500">{q.id}</td>
              <td className="max-w-[16rem] truncate py-2 font-medium text-slate-200">
                {q.title}{q.part_number ? ` — Part ${q.part_number}` : ""}
              </td>
              <td className="py-2">
                <span className={`badge ${q.post_type === "REELS" ? "bg-fuchsia-500/20 text-fuchsia-300" : "bg-cyan-500/20 text-cyan-300"}`}>
                  {q.post_type}
                </span>
              </td>
              <td className="py-2 text-slate-400">{(q.scheduled_for || "").replace("T", " ").slice(0, 16)}</td>
              <td className="py-2"><StatusBadge status={q.status} /></td>
              <td className="py-2">
                <div className="flex justify-end gap-1">
                  <button className="btn-ghost" disabled={busy} onClick={() => onReschedule(q, -1)}>-1h</button>
                  <button className="btn-ghost" disabled={busy} onClick={() => onReschedule(q, 1)}>+1h</button>
                  <button className="btn-primary" disabled={busy} onClick={() => onPublishNow(q)}>Publish</button>
                  <button className="btn-danger" disabled={busy} onClick={() => onDelete(q.id)}>Delete</button>
                </div>
              </td>
            </tr>
          ))}
          {queue.length === 0 && (
            <tr><td colSpan="6" className="py-6 text-center text-slate-500">Queue is empty.</td></tr>
          )}
        </tbody>
      </table>
    </section>
  );
}

function SettingInput({ setting, onSave }) {
  const [value, setValue] = useState(setting.value);
  useEffect(() => setValue(setting.value), [setting.value]);
  const dirty = value !== setting.value;
  return (
    <div className="flex flex-1 gap-2">
      <input className="input flex-1" value={value} onChange={(e) => setValue(e.target.value)} />
      <button className={`btn-primary ${dirty ? "" : "opacity-40 pointer-events-none"}`}
              onClick={() => onSave(setting.key, value)}>Save</button>
    </div>
  );
}
