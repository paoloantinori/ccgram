# Draft issue: restart replay starves live topics under rate penalty

Target: alexei-led/ccgram, new issue (issue-first per CONTRIBUTING).
Status: POSTED 2026-09-07 as issue #245 (user-approved).

---

Title: Restart replay starves live topics under group rate penalty; auto-trigger for the existing skip barrier

Two incidents in one month, on 2026-08-30 and 2026-09-06. Same
mechanism both times, the second one worse. Writing it up with real
numbers in case the family deserves a structural fix. The proposal at
the end reuses the existing skip barrier; nothing new would need
building.

**What happens**

Delivery tracks progress through a byte-offset watermark that only
advances when delivery settles. Under a group rate penalty, settle
stalls. Every restart replays the whole unsettled range of every
tracked session into the single per-user FIFO. With several sessions
carrying large unsettled ranges, the drain never finishes: new output
queues behind old content at 1.1 seconds per message plus 429
backoffs, and live topics go silent for hours.

Incident one, 2026-08-30: a single session with an 8MB, 1400-message
stuck watermark. Drain timeout at 1382 tasks, delivery around 10
messages per hour under penalty.

Incident two, 2026-09-06: nine sessions with unsettled ranges from
0.6MB to 52MB. Six bridge restarts during a maintenance afternoon, and
each restart replayed the full unsettled mass. Every live topic
starved until I advanced the offsets by hand, with a backup. The
skipped content is gone from Telegram and only readable through
/history.

The loop sustains itself. Penalty slows settle, the unsettled mass
persists or grows, the next restart replays it, which re-triggers the
penalty.

**What I use as a workaround**

Stop the bridge, back up monitor_state.json, fast-forward each stuck
session's offset to the file size, restart. This drops the skipped
content from Telegram delivery. It works, but it is manual and it
silently discards data.

**The gap this exposes**

The skip-barrier machinery, BacklogSkipIntent with its persisted
barrier, freeze at EOF, one notice, and commit on acknowledgement, is
the right tool for this. It bounds the replay, posts a visible notice,
and never advances past an unacknowledged boundary. But its only
trigger is the manual skip button in the status bar. During one of
these outages the status bar itself sits on the starved channel, so
the escape hatch is unreachable exactly when it is needed. Both
incidents ended with the filesystem workaround because the in-app path
was dead.

**Proposal**

Auto-trigger the existing barrier. When a session's unsettled gap
exceeds a configurable threshold, say CCGRAM_REPLAY_CAP_MB, the
monitor requests the same backlog skip on that session's behalf. Same
persisted barrier, same notice, same acknowledgement commit. No new
subsystem. The default value is a design decision: default-on makes
liveness win over completeness for stale content; default-off keeps
today's behavior and makes it opt-in. Either way the manual button
stays.

A second lever exists but I am keeping it out of scope here: fair
scheduling across per-topic queues, so one session's backlog cannot
starve its siblings while it drains.
