# Task 67: follow-up del merge upstream v4.25.0 (fork/merge-upstream-425, 2026-11-21)

Status: open (contenitore dei rilievi accettati e rinviati, tutti documentati nei commit a6469b23 e a9e167eb)

## Da /code-review high (a9e167eb)

- test_hook_lock_timeout (upstream #370) flaky sotto carico di suite completa su bird: bound 3.5 s contro import subprocess + 2 s di lock. Passa standalone e nell'run post-fix. Se ricorre in CI, alzare il bound e' una fork-side test tweak da valutare.
- Riscrittura same-inode che preserva il tail marker ora indistinguibile per design upstream (#379 ha abolito lo schedule verify; tradeoff accettato dal maintainer upstream). Nessuna azione nostra se non saperlo.
- herdr: pane.list + witness per pane a ogni ciclo di riconciliazione e' design marked-topics upstream (ordine del filo pinnato dai test public-api; il gather lo rompeva ed e' stato reventato). Se il costo IPC si sente, la cache per pass o il piggyback su agent.list vanno proposti upstream, issue-first.
- _selection_lock importato cross-modulo come privato da topic_selection (upstream-hot): promuovere a selection_lock pubblico e' una fork delta in file upstream; valutare con la prossima serie upstream o proporre upstream.

## Da /simplify (a6469b23), strutturali consciamente rinviati

- Duplication del motore di osservazione: transcript_reader mantiene digest/marker/generation privati accanto a session_protocol/transcript_source (marker window 128 vs 4096 byte; asyncio.to_thread senza la cancel-safety di run_in_worker). Il path Telegram ha bisogno di watermark che TranscriptSource non espone; adottare run_in_worker e allineare gli helper e' il primo passo meccanico se si vuole convergenza.
- Preambolo di audit triplicato (sync _run_audit, handle_sync_fix, adopt_unbound_windows): un terzo modulo con audit_with_admission() scioglie anche il ciclo lazy bidirezionale sync_command <-> topic_orchestration (i commenti nei due file lo chiedono gia').
- Lo stub di _record_automatic_admission nei test family: quando una seconda suite lo vorra', promuoverlo in tests/ccgram/_topic_admission_helpers.py insieme a una factory WindowRef condivisa (148 costruzioni inline in 37 file oggi).
- still_adoptable ha zero chiamanti produzione (solo test upstream): dargli i chiamatori naturali (prefilter sync, audit) o ritornare a cancellarlo; task-185 va annotato che il marked-mode ha reintrodotto un check admission-filtered accanto al listing liveness per scelta deliberata.

## Igiene test pre-esistente (non del merge)

- Ordine manuale topics-prima-di-sync espone leak del router globale in test_window_callbacks (@keep) e test_new_window_sync (@5): l'ordine canonico della batteria non li incontra. Reset del router nei fixture se capita ancora.

## Nota dipartite

- Il tag merge/pre-425 e' stato sostituito dal branch archive/pre-425 (il tag rompeva hatch-vcs). Rollback del merge: revert -m 1 di fd772997 + revert dei commit di follow-up, poi revert-the-revert al prossimo merge.
