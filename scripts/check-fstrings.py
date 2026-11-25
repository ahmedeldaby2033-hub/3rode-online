#!/usr/bin/env python3
"""Fail if any Python file under scripts/ has a backslash inside an
f-string expression — legal in Python 3.12+, SyntaxError on the VPS's
older Python (broke two syncs on 2026-11-25).

NOTE: ast.parse(..., feature_version=(3, 11)) does NOT catch this in 3.12,
so this uses the tokenizer: inside FSTRING_START..FSTRING_END, at brace
depth >= 1, a STRING token containing a backslash is a violation.
Backslashes in the literal part of an f-string are fine.

Usage: python3 scripts/check-fstrings.py [paths...]  (default: scripts/)
"""
import glob
import io
import sys
import tokenize


def scan(path):
    src = open(path, encoding='utf-8').read()
    hits = []
    in_f = 0
    depth = 0
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        t = tok.type
        if t == tokenize.FSTRING_START:
            in_f += 1
            depth = 0
        elif t == tokenize.FSTRING_END:
            in_f = max(0, in_f - 1)
            depth = 0
        elif in_f and t == tokenize.OP and tok.string == '{':
            depth += 1
        elif in_f and t == tokenize.OP and tok.string == '}':
            depth = max(0, depth - 1)
        elif (in_f and depth >= 1 and t == tokenize.STRING
                and '\\' in tok.string):
            hits.append((tok.start[0], tok.string[:80]))
    return hits


def main():
    roots = sys.argv[1:] or ['scripts/']
    files = []
    for root in roots:
        if root.endswith('.py'):
            files.append(root)
        else:
            files += sorted(glob.glob(root.rstrip('/') + '/**/*.py',
                                      recursive=True))
    bad = 0
    for f in files:
        for line, ctx in scan(f):
            print(f"{f}:{line}: backslash in f-string expression: {ctx}")
            bad += 1
    print(f"checked {len(files)} files, {bad} violation(s)")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
