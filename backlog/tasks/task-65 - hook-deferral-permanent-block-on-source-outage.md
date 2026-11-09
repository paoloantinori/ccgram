# Task 65: hook deferral permanently blocks plain messages after a source outage

Status: done (fix 71b5136c, deployed both bridges 2026-11-09)

- Overflow rollback: a dropped hook releases its reservation at drop time.
- Drain guard: a failing observation logs and keeps draining; one resolve per defer regardless of outcome.
- TTL backstop: deferrals expire 30s after their last defer (same horizon as queued-hook evidence); resolve tolerates an already-expired entry (the KeyError hazard two reviewers found independently).

## Incident

The Mac bridge's session-protocol source (session map / backend listing)
was unavailable for ~10 hours (37,091 "Session protocol source
unavailable" warnings at 1/s). During the outage the hook queue (256)
overflowed 575 times. Dropped evidence leaves sessions deferred forever
by design ("Lost evidence must keep affected approvals blocked until
restart" in runtime.py observe_hook). When the source recovered, the
dropped sessions stayed deferred, and every user message (message.send,
not just request.respond) hit 409 "Hook evidence awaits processing" for
hours (23:34 Nov 8 through 06:16 Nov 9) until a bridge restart.

## The design gap

The queue-full policy is correct for APPROVAL evidence (a dropped
permission request must not be auto-dismissed). But the deferral also
gates message.send, so a plain text message to an agent becomes an
opaque ❌ with no path to recovery except a restart nobody scheduled.

## Directions to evaluate

- Scope the 409 to approval-shaped actions only (request.respond) and
  let message.send through when the deferral is older than a TTL keyed
  to the hook timestamp (_HOOK_MATCH_TTL already exists for
  observe_identity); a plain message cannot forge an approval.
- Or: when refresh() recovers after an outage, re-derive deferrals from
  fresh evidence instead of keeping the stale counts.
- Also check why the source was unavailable 10h on the Mac (which
  component failed; likely tied to the herdr daemon outage window).

## Runbook (until fixed)

Bridge restart clears the in-memory deferrals: kill the ccgram process,
the LaunchDaemon respawns it, verify "extension loaded" on
~/Library/Logs/ccgram.log.
