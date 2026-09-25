# Contributing

**Scope of this file.** It describes the fork-local workflow of `sato1043/rimworld-mcp`.
It is a decision of this fork's owner. It is **not** a policy of the upstream project
(`allenmonkey970/rimworld-mcp`), and it has not been reviewed or approved by the upstream
maintainer. Do not include changes to this file in pull requests sent upstream.

This file is the source of truth for how work is carried out in this fork. Anything not
stated here follows the repository's existing conventions and `README.md`.

## Branch layout

- **`develop` is this fork's mainline**, and the default branch on `origin`.
- **`main` is not kept as a local branch.** `main` is upstream's. The remote-tracking
  refs `origin/main` and `upstream/main` are kept as mirrors of it.
- Work happens on topic branches cut from `develop`, named `task/<id>-<slug>`. Omit
  `<id>` when the change has no task document, exactly as the commit scope below is
  omitted.
- **One purpose per branch.** A branch must never mix changes bound for upstream with
  fork-local ones; split those into two branches. Integration squashes a branch into a
  single commit, so a mixed branch would weld the two together and leave nothing that
  can be sent upstream on its own.

### Keeping the fork's `main` in step with upstream

No local `main` branch is required:

```sh
git fetch upstream
git push origin upstream/main:refs/heads/main
```

### Sending a change upstream

Cut the branch from `upstream/main`, not from `develop`. `develop` carries fork-local
files (`CONTRIBUTING.md`, `CLAUDE.md`, `docs/`) that do not belong upstream.

```sh
git fetch upstream
git switch -c <slug> upstream/main
git cherry-pick <the squashed commit on develop>
```

The transplant is clean because of the one-purpose rule above: a branch bound for
upstream never touched a fork-local file, so neither does the commit it squashed into.

## Starting a piece of work

A topic branch is created together with a worktree, so that the primary checkout stays
on `develop`.

Worktrees live under `../rimworld-mcp.worktrees/<slug>`, a sibling of the primary
checkout, so that the repository directory itself stays uncluttered.

```sh
git worktree add ../rimworld-mcp.worktrees/<slug> -b task/<id>-<slug> develop
```

Two properties of this repository matter when working from a worktree:

- The RimWorld `Mods\MCP` symlink described in `README.md` points at the **primary
  checkout**. A build produced inside a worktree is not what the game loads, unless the
  symlink is repointed at that worktree.
- `MCP/1.6/Assemblies/*.dll` is **tracked** build output. Building produces a diff in the
  working tree; stage it deliberately rather than by habit.

## Finishing a piece of work

A topic branch reaches `develop` by a **direct squash merge**, with no pull request. Run
it from the primary checkout, which is already on `develop`:

```sh
git merge --squash task/<id>-<slug>
git commit
```

Then remove the worktree, and only then delete the branch — `git branch -D` fails while
the branch is checked out in a worktree.

```sh
git worktree remove ../rimworld-mcp.worktrees/<slug>
git branch -D task/<id>-<slug>
```

`-D` is required rather than `-d`: a squash merge leaves the topic branch's commits
unreachable from `develop`, so the safe delete refuses them. Confirm the squashed commit
is on `develop` with `git log --oneline -1 develop` before running it.

## Commits

Commit Lint format: `<type>(<scope>): <verb> <title>`.

- `<scope>` carries the task document ID (for example `TASK0001`); omit it when the
  change has no task document. The scope-less form used by the existing history
  (`fix: use GitHub CDN URL ...`) stays valid.
- Keep the title within 50 characters and wrap the body at 72.
- State what changed and why, not how.
- Keep documentation commits separate from code commits, and keep fork-local files (this
  file, `CLAUDE.md`, `docs/`) in commits of their own, so that they can be left out of
  pull requests sent upstream.
- Name files explicitly when staging. Do not use `git add -A` or `git add .`.

## Documents

Two fork-local trees, neither of which is sent upstream:

- `docs/records/YYYYMMDD_<topic>.md` — point-in-time evidence: what was run, what was
  observed, with sources and a stated confidence level.
- `docs/tasks/<id>_<slug>.md` — one design document per change: the plan, the work log,
  and the decisions behind it.

## Building and installing

See `README.md`. Note that the `HintPath` entries in `MCP/Source/MCP/MCP.csproj` are
hard-coded to a GOG installation path and need adjusting for other installations.
