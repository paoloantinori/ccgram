# Agent misreads relative upload path as "image never arrived"

Reported 2026-10-03 by the maintainer ("Fixa questo sul Mac"): a photo
sent to the Mac anti-vocale topic was reported by the av-mac agent as
never arrived, with the claim that the Mac bridge "is text-only and does
not download attachments".

## Root cause (verified from the session transcript)

The bridge worked end to end: the file handler downloaded the photo to
`.ccgram-uploads/photo_20261003_075203_AQADqw9r.jpg` inside the session
cwd and delivered the notification to the session. The notification
carried a RELATIVE path; the recipient agent resolved it against `~`
instead of the session cwd (Read of `/Users/pantinor/.ccgram-uploads/
...`), then a shallow `find / -maxdepth 4` also missed the file, and the
agent concluded the upload never happened. The false "text-only bridge"
story was reinforced by the workstation-protocols skill, which still
claimed it (fixed separately in cc-config).

## Fix

`_upload_and_notify` formats the agent message with the absolute
`upload_path / saved_name`; the user-facing Telegram reply keeps the
short relative form. Module docstring updated ("absolute path"). Test
`TestUploadNotifiesAbsolutePath` asserts the agent message contains the
absolute path (mock_send.await_args.args[3]).

## Verification bar

Full suite green; new test fails against the pre-fix code (mutation
checked by review: the relative form contains no absolute tmp_path).
Live check: a photo sent to a Mac topic after deploy produces a
notification with a path starting at `/`.

## Status

Done 2026-10-03, commit ff4c8980 (amended with review fixes): deployed
to bird and Mac via ccgram-bridge-deploy.sh.
