# Upstream PR plan (alexei-led/ccgram)

Lesson (2026-08-25): duplicate-check every issue against CURRENT UPSTREAM
MAIN via the GitHub API, never against the local fork. #181 (row 5 below)
slipped through exactly that way.

Process used: one issue first (CONTRIBUTING requires it), then
one-thing-per-PR branches cherry-picked off upstream main, Paolo Antinori as
author.

Outcome (2026-08-26): campaign complete; every issue closed and everything
released in v4.6.7 and v4.6.8. Continuation record, verified against the
GitHub API: for #184 and #185 the maintainer forked our commits into #192
and #191, preserving them; #183 and #186 he resolved with his own
single-commit #189, a re-implementation rather than a fork of ours (plus
his own #190 legacy-binding recovery). Caveat on #191: the final commit
merged 23 minutes after the last Greptile review round, so six P1s stood
open on the record; adjudicated 2026-08-28 against the final code, all six
are false positives (see the adjudication section). What each release
fixed is documented authoritatively in CHANGELOG.md under the version. The
v4.6.8 chores (release notes + archfit config v2) were pulled locally on
2026-08-28.

Every issue below is closed. Adoption commit per row.

| # | Issue (problem) | Ours → continuation | Adopted | Deltas |
|---|---|---|---|---|
| 1 | Telegram prompt not submitted on herdr (Enter swallowed after bracketed paste) | #183 → #189 (v4.6.7) | f2a146b | his #189 re-implemented it (0.5s, tmux-consistent); our PR-branch commit was 0ab5a2b |
| 2 | Mini App unusable from forum topics | #186 → closed via #189's is_group (v4.6.7) | f2a146b | /dashboard DM entry and expired-token page parked as optional follow-ups (offered in the #186 close comment) |
| 3 | Messages parsed but not delivered are lost on restart | #185 → #191 (v4.6.8) | df48f51 | our poison latch superseded by his receipt contract |
| 4 | Every restart announces Ready in all bound topics incl. dormant | #184 → #192 (v4.6.8) | df48f51 | our quiet latch dropped in f961f98 |
| 5 | Voice confirm keyboard easy to forget | none: duplicate | 4.6.7 rebase | upstream ships CCGRAM_VOICE_AUTOSEND since v4.6.5; the Lesson's failure case |

Follow-up work items live in the backlog, not here: TASK-9 (propose TASK-4
no-agent warnings upstream, unblocked since the campaign landed). The #191
P1 adjudication below is closed; TASK-6 stays closed.

## #191 Greptile P1 adjudication (2026-08-28, closed)

All six findings adjudicated against the adopted final code (our tree =
upstream main @ a58aaa6 plus the unrelated reaction-tracking hook;
git-diff verified on the delivery files). Every chain was re-verified
adversarially, including runtime probes of the cancellation windows:

- F1 Cancellation loses delivery receipt: FALSE POSITIVE. The receipt is
  registered before the callback await; CancelledError marks it failed,
  which blocks commit (session_monitor.py:503-519).
- F2 Undispatched offsets still commit: FALSE POSITIVE. The committable
  set is built from receipts only; receipt-free sessions never persist
  (session_monitor.py:176-188, monitor_state.py:133).
- F3 Merged receipts remain pending: FALSE POSITIVE. Merged receipts are
  captured per-attempt and settled on the dedup union
  (message_queue.py:528, 541-543).
- F4 Parse cancellation loses receipts: FALSE POSITIVE. A receipt-free
  session is never committed; restart reparses from the durable
  watermark.
- F5 Merged failure accounting disappears: FALSE POSITIVE. Dispatch state
  is populated before the send await, and the supposed merge window has
  no suspension point (verified empirically), so cancellation cannot land
  in it; RetryAfter retries carry the full merged content.
- F6 Stale receipts commit ahead: FALSE POSITIVE. The commit value is the
  max immutable receipt checkpoint, never the current parsed_offset
  (session_monitor.py:183-187, monitor_state.py:124-139).

Residual design note: the F5 analysis holds for the code as written;
inserting an await between the merge drain and the dispatch-state
population (message_queue.py:269 through 401) would silently reopen the
stranded-receipt hazard. Add a guard comment if that area is ever
extended.

## Candidate features (verified 2026-08-28 against upstream main @ a58aaa6)

git grep evidence, recorded so the check does not need re-running before
each proposal (re-verify anything older than a few upstream releases):

| Feature | Local | Upstream main | Issue |
|---|---|---|---|
| No-agent warnings | TASK-4 (done) | absent | #198 OPEN (filed 2026-08-28) |
| Direct option buttons (1/2/3, yes/no) for interactive prompts | TASK-8 (done) | absent | #193 OPEN (filed 2026-08-26) |
| Per-topic identity icons (forum icon set) | 0c65419..d46de46 | absent | #197 OPEN (filed 2026-08-27) |
| /dashboard DM entry + expired-token page | parked (offered in the #186 close comment) | absent | #194 OPEN (filed 2026-08-26) |
| Reaction-triggered custom actions ([reactions] in toolbar.toml) | TASK-7 (done) | toolbar exists; no [reactions] surface | #195 OPEN (filed 2026-08-26) |
| TTS robustness (Retry-After on 429, fallback chain) | 4f9fd45, c934ed9 | tts/ package EXISTS upstream | not filed; delta is fixes, propose alongside voice interest |

Issues #193-#195 and #197 were filed 2026-08-26/27 (the candidate table in
this doc briefly understated this: it verified code on main but not the
issue tracker; the #181 lesson applies to proposals too). All candidates
except TTS robustness are now open issues. Next per process: one-thing-
per-PR branches cherry-picked off current upstream main as the maintainer
engages. The #191 P1 adjudication (below) closed with no confirmed bugs,
so no bug report followed.

## Delivery-under-rate-pressure family (2026-08-29/30 incidents)

Three issues from one incident arc, all mechanism-verified on upstream
main @ a58aaa6, all with local fixes already landed on port-4.6 (the PR
offer is a cherry-pick of our validated fix):

| Issue | Bug | Local fix (commit) |
|---|---|---|
| #199 OPEN (2026-08-29) | restart first-paint burst + swallowed RetryAfter = self-sustaining editForumTopic flood loop gating all Bot API traffic | 0453275 (cooldown + pacing), 2c4494a (icons half) |
| #205 OPEN (2026-08-30) | queue-idle-only watermark commit: restart under sustained output replays the whole unsettled prefix into the single per-user FIFO; under a group rate penalty the drain never finishes, so the replay is perpetual and live topics starve | 2f00e81 (settled-prefix commit); upstream PR #207 (2026-08-30) |
| not filed | PTB AIORateLimiter's per-group send bucket + global retry-after event starve editForumTopic (renames/icons) behind a busy outbound queue | 6e0f6c6 (TopicEditAwareRateLimiter); file when the #199/#205 conversation starts, same subsystem |

The #205 evidence (8MB/1400-message stuck watermark, 1382-task drain
timeout, ~10 msg/hour under penalty) is in the issue; the recognition
pattern and manual unblock procedure are in project memory.

## Continuation (2026-09-04)

Status refresh: #199 and #205 both CLOSED 2026-08-31 (via PRs #206 and
#207, ours, merged upstream and shipped in v4.9.x). The limiter-bypass
row is the only one still unfiled; its trigger condition ("when the
#199/#205 conversation starts") has fired. The #195/#197 extension-seam
conversation now has drafts and a public artifact
(github.com/paoloantinori/ccgram-ext); nothing upstream is posted
without explicit user approval. This plan file was lost in the
2026-08-31 reset-integration and restored from the pre-reset tip
(14c727a) on 2026-09-04.
