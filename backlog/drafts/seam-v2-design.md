# Extension seam v2: base-layer auth and capability gating (DRAFT)

Status: design draft, not scheduled. Companion to the future upstream
loader offer (see docs/extension-seam.md for v1). Informed by the
layered reference model verified in NousResearch/hermes-agent
(umbrella #64176, reactions slice #68431, base-layer auth follow-up
#74697, merged implementation PR #82063): normalized envelopes,
observer hooks separate from platform actions, post-auth enforced at
the base layer, writes gated by capability.

## What v1 has, and where it knowingly deviates

- Normalized outbound envelopes: yes (`message.delivered`,
  `topic.bound`; plain kwargs, no SDK objects).
- Inbound events: NO. The reactions feature registers a raw PTB
  MessageReactionHandler and reads the platform Update itself. The
  consumer boundary does see SDK objects, exactly what the reference
  model forbids.
- Authorization: at the consumer call site
  (`ccgram_ext.reactions.handle_reaction_update` checks
  `is_user_allowed` itself). This is the anti-pattern hermes #74697
  documents: a second consumer of the same surface can ship without
  the gate. We said so in the #195 draft ("I would move mine before
  proposing anything here").
- Platform writes: unrestricted. The ext reaches
  `multiplexer.send_keys`, `client.send_document/send_voice`,
  `edit_forum_topic` via imports. No capability notion.

## v2 shape (smallest version faithful to the reference)

1. Core emits `reaction.received` (chat_id, message_id, actor_user_id,
   emoji delta, tracked context) from a single base-layer site that
   applies the allowed-user gate BEFORE emitting. Consumers never
   register a reaction handler; `register_ptb_handler` stops being
   needed for this feature. Inert by default preserved: with no
   listeners the handler is not even registered.
2. `api.capability(name)` granted at registration; the seam exposes
   scoped write handles instead of raw singletons
   (`api.terminal_write()` -> multiplexer send for claimed windows,
   `api.chat_send()` -> rate-limited send). v1 imports keep working
   (deprecation path, not a break).
3. Events registry: the set of emitted events becomes a documented,
   add-only contract table in docs/extension-seam.md.

## Why now and not now

The upstream offer gains its strongest form when the seam can be
presented as "observer events + gated writes, auth at the base layer",
because that is the direct answer to the maintainer's two objections
(hidden state -> normalized envelopes we already have; actions by
mistake -> capability gating makes the blast radius explicit per
extension). But implementing v2 before the offer is not required: the
current v1 runs in production and the migration is additive. Trigger:
start this when the decision to open the upstream conversation is
taken, so the offer lands with v2 semantics from day one.
