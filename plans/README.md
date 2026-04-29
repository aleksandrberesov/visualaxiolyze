# Plans

Phased implementation plans for this project. The workflow:

1. **Make a plan** with Claude (or by hand). Save it under `active/`.
2. **Execute phases manually**, one at a time, with Claude's help in VS Code or
   the terminal. Each phase should land as one or a few commits.
3. **Archive** completed plans by moving them to `done/`.

## Layout

```
plans/
├── README.md          ← this file
├── template.md        ← copy this when starting a new plan
├── active/            ← plans currently in progress
└── done/              ← completed plans (kept for history)
```

## File naming

`YYYY-MM-DD-short-slug.md`

Examples:
- `2026-04-29-ui-ux-redesign.md`
- `2026-05-12-schema-validation.md`

The date is when the plan was *made*, not when work started or finished.

## Plan structure

Use `template.md` as a starting point. Each plan contains:

- **Context** — what triggered the plan (link to discussion, issue, decision).
- **Phases** — numbered, each phase a coherent chunk that can be reviewed and
  committed on its own. Each phase lists:
  - Files touched (with line numbers if useful).
  - Concrete steps.
  - What "done" looks like.
- **Execution order** — dependencies between phases, recommended sequence.
- **Status** — checkbox per phase, updated as work lands.

## Running a phase with Claude

Start a fresh Claude Code session and paste:

> Continue plan `plans/active/<file>.md` — Phase N. Execute the steps in that
> phase only. Stop after the phase is complete so I can review.

Claude will read the plan from disk, make the changes, and stop. You review,
commit, then start the next phase.

## When a plan is done

1. Mark all phases ✅ in the plan file.
2. Add a "Completed" line at the top with the date.
3. Move the file from `active/` to `done/`.
4. Commit.

## Why this workflow

- **Plans live in the repo**, not in chat history — survives across sessions,
  branches, machines, and Claude tools (CLI, VS Code, web).
- **Phases keep blast radius small** — easy to review, easy to revert.
- **Manual execution between phases** keeps a human in the loop on every
  meaningful change while still letting Claude do the typing.
