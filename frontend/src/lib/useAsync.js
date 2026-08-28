import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Run an async fetcher and track loading/error/data.
 *
 * The generation counter is the point: switching runs fires a second fetch
 * while the first is still open, and without it a slow response for the
 * previous run can land after the fast one for the current run and overwrite
 * the correct data with stale data.
 */
export function useAsync(fetcher, deps = [], { skip = false } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: !skip });
  const generation = useRef(0);

  const run = useCallback(async () => {
    const mine = ++generation.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await fetcher();
      if (mine === generation.current) setState({ data, error: null, loading: false });
    } catch (err) {
      if (mine === generation.current)
        setState({ data: null, error: err.message ?? String(err), loading: false });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    if (skip) return;
    run();
  }, [run, skip]);

  return { ...state, reload: run };
}
