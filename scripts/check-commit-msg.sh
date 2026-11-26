#!/bin/sh
# The commit message must be a conventional commit: type(optional scope): subject. Merge commits are left alone.
first=$(sed -n '1p' "$1")
case "$first" in "Merge "*) exit 0 ;; esac
echo "$first" | grep -Eq '^(feat|fix|docs|chore|refactor|test|style|perf|build|ci|revert)(\([^)]+\))?!?: .+' && exit 0
echo "Not a conventional commit message: '$first'"
echo "Use 'type: subject', with type one of feat, fix, docs, chore, refactor, test, style, perf, build, ci, revert."
exit 1
