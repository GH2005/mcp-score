---
name: mcp-score-audit
description: >
  Audit-and-repair campaign for the mcp-score MCP server and the
  mcp-score-bridge MuseScore QML plugin: enumerate every wire command and
  every MCP tool from SOURCE, exercise each one against a live MuseScore,
  fix what is broken, implement what is missing, then refresh the
  musescore-bridge skill so the documented state matches reality again.
  Use when asked to "test every wire command", "test every MCP tool",
  "audit mcp-score", "re-verify the bridge", "the plugin/server is broken
  again", "find feature gaps in mcp-score", "add a new wire command or MCP
  tool", or when resuming a test-and-fix campaign over the plugin or the
  server. Distinct from the musescore-bridge skill: that one records the
  current verified state, this one is the procedure that regenerates it.
metadata:
  version: "1.0"
---

# mcp-score audit & repair

A **process** skill. The `musescore-bridge` skill holds the current
verified state (support matrix, safety rules); this one is the procedure
that regenerates that state after the plugin or server has drifted, broken,
or grown a gap.

## Rule 0 — the inventory comes from source, never from documentation

Enumerate the surfaces to test by reading
`src/mcp_score/musescore/mcp-score-bridge.qml` and `src/mcp_score/tools/`.
**Do not seed the audit from `agent-playbook.md` or any doc** — those are
lagging artifacts and have been wrong. On 2026-07-22 the playbook was
missing 5 of 22 wire commands and 11 of 23 MCP tools by name, and the gap
was found only by diffing the docs against source with the Phase 5 script
— reading the playbook could never have revealed it. A surface absent
from the docs is exactly the surface most likely to be broken or
unimplemented, so a doc-derived checklist is blind in precisely the wrong
place.

## Phase 1 — Enumerate from source

Run from the repo root. These are verified to work in this environment
(git-bash `grep` here has no `-P`, hence `sed`):

```bash
Q=src/mcp_score/musescore/mcp-score-bridge.qml

# (A) Wire commands — the handleMessage dispatcher. The full command surface.
sed -n 's/.*case "\([A-Za-z]*\)":[[:space:]]*return handle.*/\1/p' $Q | sort -u

# (B) Actions valid INSIDE processSequence — a second, smaller switch.
grep 'case "' $Q | grep -v 'return handle' \
  | sed -n 's/.*case "\([A-Za-z]*\)".*/\1/p' | sort -u

# (C) MCP tools.
grep -h -A3 "@mcp.tool()" src/mcp_score/tools/*.py \
  | sed -n 's/^\(async \)\{0,1\}def \([A-Za-z_]*\).*/\2/p' | sort -u
```

**The QML has two switches, and the asymmetry is a real gap class.**
Commands in (A) but not (B) cannot be used inside `process_live_sequence`.
Compute the difference and decide, per command, whether that is deliberate
or a gap worth filling:

```bash
comm -23 <(sed -n 's/.*case "\([A-Za-z]*\)":[[:space:]]*return handle.*/\1/p' $Q | sort -u) \
         <(grep 'case "' $Q | grep -v 'return handle' \
           | sed -n 's/.*case "\([A-Za-z]*\)".*/\1/p' | sort -u)
```

Record the three lists as the campaign checklist before touching anything.
Counts at last audit (2026-07-22): 22 wire commands, 15 sequence actions,
23 MCP tools. Treat those as a staleness signal, not as the answer —
re-derive them.

## Phase 2 — Stand up the rig

1. MuseScore running with the plugin dock launched (**Plugins →
   mcp-score-bridge**). The dock must be relaunched after every MuseScore
   restart, or nothing listens on `ws://localhost:8765`.
2. Confirm the _running_ plugin is the one on disk: `getScore` →
   `pluginVersion`. A stale dock silently invalidates every result.
3. Use a **disposable score**, never the user's real work. The live suite
   refuses unless the title contains `untitled`, `scratch`, or `mcp`
   (override: `MCP_SCORE_LIVE_ANY_SCORE=1`). Apply the same discipline to
   manual testing — several commands can crash MuseScore and take all
   unsaved work with them.
4. Know the restart matrix before you edit:
   - **`.qml` change** → **ask the user to restart MuseScore** and
     relaunch the dock. You cannot do this yourself; say so explicitly and
     wait. Re-confirm via `pluginVersion`.
   - **Python change** → restart the MCP client (Claude Code) for tool
     changes; the live suite picks up source directly via
     `uv run --project`, no restart.

## Phase 3 — Exercise every surface

Work the Phase 1 checklist item by item. For each:

- **Verify by export, not by reply.** A reply is not evidence. Snapshot
  and inspect the MusicXML. (The `musescore-bridge` skill's ground-truth
  doctrine covers the mechanics; follow it rather than re-deriving it.)
- Test the wire command _and_ its MCP wrapper — they fail independently
  (a working command with a broken/absent tool is a gap, and vice versa).
- Where the command is also a sequence action, test it inside
  `process_live_sequence` too; the sequence path has its own handler code.
- Anything already known-fatal (crashes or corrupts) stays behind its
  guard. Only probe it on a disposable, **already-saved** score with the
  user's explicit go-ahead, and warn them a crash is the likely outcome.

Classify each surface: **works** / **broken** (record the exact failure
mode and how it presents) / **missing**. That classification is the input
to Phase 5 — capture it as you go, not from memory afterwards.

## Phase 4 — Fix or implement

End-to-end path for a command:

1. **QML** — add/repair the `case` in `handleMessage` plus its `handle…`
   function: validate params first, wrap mutations in
   `startCmd`/`try`/`finally` `endCmd`. Add it to the `processSequence`
   switch too if it should be sequenceable.
2. **Bridge** — convenience method in `src/mcp_score/bridge/musescore.py`.
3. **Tool** — `@mcp.tool()` in `src/mcp_score/tools/`, guarded with
   `connected_bridge()` / `check_measure` / `_require_musescore`.
4. **Tests** — mocked (runs in CI) **and** live (delta-scoped MusicXML
   diff, so a dirty score cannot cause a false pass or failure).
5. **Bump the plugin `version`** in the QML whenever the QML changes —
   that is what makes `pluginVersion` a usable staleness check.

For a defect that is MuseScore's rather than ours, do not paper over it:
guard the call, make the tool refuse with an explanation, and record the
failure mode. An honest refusal beats a silent corruption.

## Phase 5 — Refresh the skills (do not skip)

The campaign is not done when the code works; it is done when the
documented state matches reality.

1. Update the `musescore-bridge` skill's `agent-playbook.md`: move rows
   between the works/broken tables, add new surfaces, and update the
   banner's **verification date** and **plugin version**.
2. Update the five safety rules in that skill's `SKILL.md` only if a
   safety-relevant fact changed. Keep them a subset — the playbook stays
   the single source of truth; do not let the two drift into rival lists.
3. **Prove coverage** — every wire command and every MCP tool must appear
   by name in the playbook. This is the check that would have caught the
   2026-07-22 gap:

```bash
PB=.claude/skills/musescore-bridge/agent-playbook.md
Q=src/mcp_score/musescore/mcp-score-bridge.qml
{ sed -n 's/.*case "\([A-Za-z]*\)":[[:space:]]*return handle.*/\1/p' $Q
  grep -h -A3 "@mcp.tool()" src/mcp_score/tools/*.py \
    | sed -n 's/^\(async \)\{0,1\}def \([A-Za-z_]*\).*/\2/p'
} | sort -u | while read -r n; do
  grep -q "\b$n\b" "$PB" || echo "MISSING FROM PLAYBOOK: $n"
done
```

4. Format and test:

```bash
uv run --with "nodejs-bin[cmd]" python -m nodejs.npx --yes prettier@3 --write <changed .md files>
uv run pytest -q                      # CI set; excludes live
uv run pytest -m live tests/live -q   # needs MuseScore + dock
```

## Environment notes

- `npx`/`node` are not on PATH; the `nodejs-bin` PyPI wrapper above is how
  prettier runs here.
- A bare `python` is the Microsoft Store stub. Use `uv run python`.
- `gh` is not installed. For PRs against the fork, use the git-credential
  token with `curl` against the GitHub REST API.
- Shell working directory can reset between turns — use absolute paths or
  `cd` into the repo in each call.
