# Cover the renamed saved name in the upload notification test

From greptile-apps[bot] (P2) on alexei-led/ccgram#296, merged 2026-10-03
as aabbbe5b by alexei-led: TestUploadNotifiesAbsolutePath mocks
_download_and_save to return "a.txt" while the requested filename is
also "a.txt", so nothing pins that the notification carries the RENAMED
saved name when _unique_dest de-duplicates a collision (a.txt -> a_1.txt).

## Why it is real

The wiring in _upload_and_notify uses the return value of
_download_and_save (saved_name) for the agent message. A regression that
builds the message from the original filename argument instead would pass
the current test because the two are identical in the mock.

## Fix shape

One extra case in TestUploadNotifiesAbsolutePath (or a parametrized
variant): mock _download_and_save to return "a_1.txt" for filename
"a.txt" and assert the agent message contains the absolute path with
a_1.txt. Applies to both fork and upstream tests; upstream only if a
future PR rides anyway, not worth a standalone upstream PR.

## Verification bar

Mutation check: swap saved_name for filename in the claude_msg format
call and watch this new case fail while the existing one stays green.

## Status

Open. Trivial; pick up with the next fork touch of file_handler tests.
