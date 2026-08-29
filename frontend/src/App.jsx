import { useCallback, useEffect, useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import Navbar from "./components/Navbar.jsx";
import ScrollToTop from "./components/ScrollToTop.jsx";
import Chat from "./pages/Chat.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Simulation from "./pages/Simulation.jsx";
import { RunContext } from "./lib/runContext.js";
import { useEvents } from "./lib/useEvents.js";
import { getOverview, getRuns } from "./api.js";

/**
 * Two pieces of genuinely global state, and nothing else.
 *
 * The first is which simulated world every page is reading. The second is the
 * event-bus subscription — held here rather than per page precisely because
 * pub/sub is a property of the application: one `EventSource` feeds the navbar
 * indicator, the dashboard feed and the simulation sidebar at once, and
 * navigating between pages does not drop the stream or replay it a second time.
 *
 * Everything else a page needs, it fetches for itself. There are three pages and
 * no shared mutations, so a store would be ceremony.
 */
export default function App() {
  const [runs, setRuns] = useState([]);
  const [runId, setRunId] = useState(null);
  const [status, setStatus] = useState(null);

  // Deliberately unfiltered by run: the bus is the story of the whole session,
  // including the reset and inject events that create a run in the first place.
  const bus = useEvents({ replay: 80, limit: 300 });

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

  const select = useCallback(async (id) => {
    setRunId(id);
    try {
      const ov = await getOverview(id);
      setStatus({ run_id: ov.run_id, label: ov.label, scenario: ov.scenario });
    } catch (err) {
      setStatus({ error: err.message });
    }
  }, []);

  const busSummary = {
    connected: bus.connected,
    count: bus.events.length,
    backend: bus.meta?.backend,
  };

  return (
    <BrowserRouter>
      <RunContext.Provider value={{ runs, runId, setRunId: select, refresh, status }}>
        <ScrollToTop />
        <Navbar status={status} bus={busSummary} />
        <Routes>
          <Route path="/" element={<Dashboard bus={bus} />} />
          <Route path="/simulation" element={<Simulation bus={bus} />} />
          <Route path="/chat" element={<Chat bus={bus} />} />
          <Route path="*" element={<Dashboard bus={bus} />} />
        </Routes>
      </RunContext.Provider>
    </BrowserRouter>
  );
}
