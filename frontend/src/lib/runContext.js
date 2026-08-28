import { createContext, useContext } from "react";

/** Which simulated world the UI is reading. Provided once by App. */
export const RunContext = createContext({
  runs: [],
  runId: null,
  setRunId: () => {},
  refresh: async () => {},
  status: null,
});

export const useRun = () => useContext(RunContext);
