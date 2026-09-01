# OpenPype Agent Context

## Overview

This is the **OpenPype** pipeline monorepo (`openpype/` core, `igniter/` bootstrapper,
`server_addon/` AYON addon definitions, `tools/` build & dev scripts, `tests/` pytest
suites, `website/` + `docs/` documentation). Nested at
`openpype/addons/bumpybox_addon/` is a **separate repository** with its own
`AGENTS.md` and its own delegation hook — leave it to that contract.

## Mode Awareness

**Before performing any file edits or expensive exploration, check the current agent mode:**

- In **ask** or **plan** mode — do not attempt to edit files. Provide plans, explanations, and recommendations only. Avoid deep token-heavy codebase traversal unless necessary to answer the question.
- In **edit** (agent) mode — proceed with implementation, file edits, and thorough exploration as needed.

This prevents wasting tokens on file-editing tool calls that will be rejected in non-edit modes.

## Orchestrator Delegation Contract

You are the orchestrator, not the implementer. **Your only directly-editable
path is `docs/`.** Everything else — `openpype/`, `igniter/`, `server_addon/`,
`tools/`, `vendor/`, `website/`, `tests/`, and root files (`start.py`,
`app_launcher.py`, `pyproject.toml`, `setup.py`, `AGENTS.md`, `README.md`) —
must be changed through a subagent.

**Mandatory delegation:**

| Work | Delegate to | How |
|------|-------------|-----|
| Write/edit anything under a `tests/` folder | `test-writer` | `runSubagent` with `agentName: "test-writer"` |
| Write/edit anything else outside `docs/` | `builder` | `runSubagent` with `agentName: "builder"` |
| Read-only search / large or generated file reads | `explorer` | `runSubagent` with `agentName: "explorer"` |

**Hard gate — self-check before EVERY file edit:** "Is the target path outside
`docs/`?" — **Yes → STOP**, delegate to `builder`/`test-writer` instead. You may
always run commands, read small files, and run tests yourself to verify.

**Deterministic guardrail:** [.github/hooks/enforce-delegation.ps1](.github/hooks/enforce-delegation.ps1)
hard-blocks (exit code 2) any file create/edit tool call outside `docs/` unless a
subagent is active, and blocks direct orchestrator reads of files > 50 KB
(delegate those to `explorer`). It fails open on internal errors so it can never
brick legitimate editing — the contract above still applies regardless.

## Settings Before Code

**Check settings first.** Many behaviours (loader/creator/publish plugin
defaults, enabled state, name templates, option defaults, host presets) are
already exposed as OpenPype/AYON settings. If the request can be satisfied by
changing a project setting, say so and stop — do not edit code.

Self-check before any code change:

1. Does a setting already control this? Search `openpype/settings/defaults/`,
   `openpype/settings/entities/schemas/`, and `server_addon/<addon>/server/settings/`.
2. If yes → tell the user which setting and where (Project Settings path), and
   do not touch the plugin code.
3. Only if no setting exists → change code, and prefer adding a setting over
   hardcoding a new default.

Never change a shipped default in `openpype/settings/defaults/` or
`server_addon/` to fix one user's project — project-level overrides are the
correct place. Changing a shipped default is a no-op for any project that
already overrides it.

## Key Reference Directories

- **`openpype/pipeline/`** — base classes and pipeline interfaces (`Creator`, `Collector`, `Validator`, `Integrator`, `Loader`). Reference when implementing publish plugins.
- **`openpype/hosts/`** — host integrations (Maya, Houdini, Nuke, TVPaint, ...) and their plugins.
- **`openpype/modules/`** — optional modules/addons (ftrack, deadline, timers manager, ...).
- **`openpype/settings/`** — legacy settings schemas and defaults.
- **`server_addon/`** — AYON-side addon definitions; usually must be updated alongside `openpype/settings/`.
- **`tests/`** — pytest unit + integration suites (see [tests/README.md](tests/README.md)).

## Communication Style: Caveman
To reduce output tokens and improve clarity, adopt a "caveman" communication style:
- Use the fewest words possible to convey the information.
- Remove filler, pleasantries, and unnecessary explanations.
- Keep technical details, code, and commands byte-for-byte exact.
- Example: Instead of "The reason your React component is re-rendering is likely because...", use "Inline object prop = new ref = re-render. Wrap in useMemo."
- Maintain high technical accuracy while minimizing word count.
