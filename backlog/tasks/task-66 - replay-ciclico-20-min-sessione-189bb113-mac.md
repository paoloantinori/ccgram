# Task 66: replay ciclico ogni 20 minuti della coda finale di session 189bb113 (Mac)

Status: open (incident 2026-11-09, Mac bridge, in corso)

## Sintomi

- Il topic 42200 (apitomy-axiom) riceve una terna identica di messaggi
  (1987/59/208 char) ogni 20 minuti (:08/:28/:48), da ieri 23:34 a oggi
  in corso. Il transcript di quella sessione NON ha entry nuove dal
  7 novembre: sono byte vecchi riletti e riconsegnati.
- Il watermark persistito (monitor_state tracked_sessions) e' a EOF
  (43728622, gap 0) e parsed_offset e' None: la deferral di consegna
  vive in memoria e qualcosa ogni 20 minuti riparte da un offset
  anteriore.
- Ieri 16:58-17:08 subito dopo un riavvio del bridge (16:57:31,
  causa del riavvio ancora da identificare: lancd non mostra spawn di
  com.user.ccgram in quella finestra) 11 consegne identiche a cadenza
  ~50s, poi quiete, poi ripresa alle 00:08.
- Il medesimo agente stamattina 16:59 riceveva StopFailure "prompt is
  too long: 1145061 tokens" (transcript 43.7 MB): il suo workflow e' in
  loop da ieri, ma il transcript dimostra che NON e' lui a generare i
  contenuti riconsegnati.

## Da indagare

- Chi riazzerca l'offset in-memory ogni 20 minuti per questa sessione
  (periodic task? reconciler che riadopta da session_map con offset
  stantio? seconda traccia fantasma non persistita?).
- Perche' il riavvio delle 16:57:31: chi ha restartato il daemon
  (launchd non mostra lo spawn; verificare system log e cron).
- L'interazione con il fix di successione workspace: la sessione e'
  nella famiglia ha-tuya (cwd $HOME) toccata dal fix.

## Mitigazione nota

Restart del bridge Mac (kill + respawn del daemon) azzera i blocchi
in-memory e ferma il ciclo finche' non riparte.

## Evidenze aggiuntive (2026-11-09 pomeriggio)

- Il transcript 189bb113 (43.7 MB) e' fermo al 8 nov 15:56: NESSUNA entry
  nuova dal momento del caos. Le consegne ripetute sono byte vecchi
  riletti: non e' l'agente che produce output identico.
- Il binding del window 86a597df (la sessione home) e' MIGRATO dal topic
  auto-creato 153932 al topic 172265: il window e' vivo, bindato e con
  la succession fix ora e' coperto dai prossimi /clear.
- La deferral che genera i replay vive SOLO in memoria: il watermark
  persistito e' a EOF (43728622, gap 0) e parsed_offset non e' persistito
  per quella sessione. Qualcosa ogni ~20 minuti riazzerà l'offset
  in-memory.
- Candidati da indagare: il reconciler che riadopta la sessione dal
  session_map a ogni giro (offset di adoption?), un timer della herdr
  agent-status push, o il ciclo di riconciliazione dei target.

## Chiusura incidente sul campo

Restart del bridge Mac alle ~15:20 CET ha fermato il burst (dopo 11
consegne). Il ciclo e' ripreso alle 00:08. La mitigazione resta il
restart; la prevenzione richiede il pin del meccanismo.
