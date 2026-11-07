# TASK-66: deploy contract dice "log timestamps are local time", il log e' UTC

Verificato 2026-11-07 sul Mac: riga di log `13:46:49 [debug] Dispatching...`
scritta NELLO STESSO SECONDO in cui `date -u` sul Mac dava `13:46 UTC`
(ora locale 14:46 CET). Il CLAUDE.md del fork (deploy contract, sezione
manual form) afferma "Log timestamps are local time, not UTC": deriva
nata probabilmente col cambio ora legale (la nota workstation-protocols
storica diceva "UTC, due ore indietro rispetto al CEST" estate).

Costo: chi diagnostica il bridge confrontando il log con l'orologio
locale conclude che il processo e' zitto/wedged quando e' vivissimo
(2026-11-07: kill superfluo del runner per questo motivo).

Cura: correggere la riga del CLAUDE.md ("UTC, +1h rispetto a CET
invernale, +2h CEST estivo") e fare un giro su eventuali script che
confrontano timestamp del log con `date` locale.

DoD: docs fix + grep sugli script del repo che usano date/locale col
log. Nessun codice.
