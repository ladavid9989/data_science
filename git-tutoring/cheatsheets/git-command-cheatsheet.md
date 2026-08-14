# Git Command Cheatsheet

## Inspect First

```bash
git status
git branch
git log --oneline --graph --decorate --all
```

## Clone and Enter a Repo

```bash
git clone https://github.com/<owner>/<repo>.git
cd <repo>
```

## Create and Switch Branches

```bash
git switch -c my-new-branch
git switch main
git switch my-existing-branch
```

## Stage and Commit

```bash
git add README.md
git commit -m "Update README"
```

## Push and Pull

```bash
git push origin my-branch
git pull
```

## Compare Changes

```bash
git diff
git diff --staged
```

## Undo Carefully

Unstage a file:

```bash
git restore --staged README.md
```

Discard local edits in one file only when you are sure:

```bash
git restore README.md
```

Do not use destructive commands such as `git reset --hard` unless you fully understand the consequence.

## Collaboration Commands

Bring latest `main` into your branch:

```bash
git switch main
git pull
git switch my-branch
git merge main
```

## Useful GitHub Terms

| Term | Meaning |
|---|---|
| Repository | Project folder tracked by Git |
| Commit | Saved checkpoint |
| Branch | Separate line of work |
| Pull request | Proposal to merge changes |
| Merge | Combine branch changes |
| Conflict | Git needs human help to combine changes |
| Fork | Your own copy of someone else's GitHub repo |
| Clone | Download a repo to your computer |
