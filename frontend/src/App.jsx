import { useCallback, useEffect, useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import Navbar from "./components/Navbar.jsx";
import Chat from "./pages/Chat.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Simulation from "./pages/Simulation.jsx";
import { RunContext } from "./lib/runContext.js";
import { getOverview, getRuns } from "./api.js";

/**
 * The one piece of state that is genuinely global: which simulated world every
 * page is reading. Everything else a page needs, it fetches for itself — there
 * are three pages and no shared mutations, so a store would be ceremony.
 */
export default function App() {
  const [runs, setRuns] = useState([]);
  const [runId, setRunId] = useState(null);
  const [status, setStatus] = useState(null);

  const refresh = useCallback(async (preferred) => {
    try {
      const list = await getRuns();
      setRuns(list.runs);
      const next = preferred ?? list.current_run_id;
      setRunId(next);
      const ov = await getOverview(next);
      setStatus({ run_id: ov.run_id, label: ov.label, scenario: ov.scenario });
      return next;
    } catch (err) {
      setStatus({ error: err.message });
      return null;
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const select = useCallback(
    async (id) => {
      setRunId(id);
      try {
        const ov = await getOverview(id);
        setStatus({ run_id: ov.run_id, label: ov.label, scenario: ov.scenario });
      } catch (err) {
        setStatus({ error: err.message });
      }
    },
    [],
  );

  return (
    <BrowserRouter>
      <RunContext.Provider value={{ runs, runId, setRunId: select, refresh, status }}>
        <Navbar status={status} />
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/simulation" element={<Simulation />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="*" element={<Dashboard />} />
        </Routes>
      </RunContext.Provider>
    </BrowserRouter>
  );
}
