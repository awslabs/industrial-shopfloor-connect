# Project rules

## TOP PRIORITY — Git is off-limits

**NEVER run any git command that changes repository state.** Git is the user's business, not yours.

Specifically, do NOT:
- create, switch, rename, or delete branches (`git branch`, `git checkout -b`, `git switch`)
- stage, commit, or amend (`git add`, `git commit`)
- merge, rebase, cherry-pick, or reset (`git merge`, `git rebase`, `git cherry-pick`, `git reset`)
- push, pull, or fetch (`git push`, `git pull`, `git fetch`)
- stash, tag, or otherwise mutate refs or the working tree via git

Read-only inspection is fine (`git status`, `git log`, `git diff`, `git branch --show-current`,
`git merge-base`, `git merge-tree` dry-runs). If a task seems to need a state-changing git
operation, STOP and ask the user to do it themselves.

## AWS access is off-limits

**NEVER use the AWS CLI or any AWS SDK to try to obtain account access.** Do not run
`aws sts get-caller-identity`, `aws configure`, `aws login`, `aws sso login`, or any CLI/SDK call
whose purpose is to acquire, refresh, or probe credentials or account access. If a task seems to
need AWS access, STOP and ask the user to perform the AWS step themselves.
