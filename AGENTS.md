# Agent notes

- Every matching log email carries the previous **12 hours** of Nginx logs,
  split into six 2-hour chunks (`<site>_2h_<stamp>.log` plus
  `<site>_2h_<stamp>-proxy.log`). Each site CN/KR/EN/JP is a separate email.
- For a "last N hours" request, use the newest `ceil(N / 12)` emails per site
  (12h -> 1, 24h -> 2, 48h -> 4). Select them by `emails.received_at` and
  resolve paths through the `attachments` table; stored paths are hashed.
- Log timestamps inside the files are authoritative for line filtering; the
  12-hour coverage ends at send time, not at a round clock hour.
- `*-proxy.log` is universal-service's detailed log and is skipped in
  directory scans for now; only the `2h` access logs count.
- See `README.md#log-coverage-per-email` for the same rule in context.
