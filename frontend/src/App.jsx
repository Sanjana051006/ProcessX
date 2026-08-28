import { useEffect, useState } from "react";
import { getHealth } from "./api";

export default function App() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getHealth().then(setHealth).catch((e) => setError(e.message));
  }, []);

  return (
    <main>
      <h1>ProcessX</h1>
      <p className="sub">NovaCart fulfilment — agentic process intelligence</p>

      {error && <p className="bad">Backend unreachable: {error}</p>}
      {!health && !error && <p>Checking backend…</p>}
      {health && (
        <dl>
          <dt>Backend</dt>
          <dd className="ok">{health.status}</dd>
          <dt>journal_mode</dt>
          <dd className={health.journal_mode === "wal" ? "ok" : "bad"}>
            {health.journal_mode}
          </dd>
          <dt>Tables</dt>
          <dd className={health.missing_tables.length ? "bad" : "ok"}>
            {health.tables.length} / 8
          </dd>
          <dt>Indexes</dt>
          <dd className={health.indexes.length === 5 ? "ok" : "bad"}>
            {health.indexes.length} / 5
          </dd>
        </dl>
      )}
    </main>
  );
}
