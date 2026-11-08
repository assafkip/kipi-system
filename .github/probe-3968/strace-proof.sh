#!/usr/bin/env bash
# TEMPORARY ASK-3968 probe. Makes the lost mkdir race happen on purpose: strace
# holds the create syscall for 2 s (only syscalls on that one path, via -P),
# after the binary has already checked the path, and a rival process creates
# the directory inside that window. The trace shows what the kernel answered
# and what the binary reported. Then the same window for python os.mkdir and
# for a bash O_EXCL redirect, as controls.
set -u
T="$(mktemp -d)"
echo "mkdir binary: $(readlink -f "$(command -v mkdir)")"
mkdir --version 2>&1 | head -1

echo "== 1. mkdir binary, create syscall held 2 s, rival creates the dir at 0.5 s"
strace -f -o "$T/mkdir.trace" -P "$T/race-a" \
  -e inject=mkdir,mkdirat:delay_enter=2000000 mkdir "$T/race-a" &
P=$!
sleep 0.5; python3 -c "import os,sys; os.mkdir(sys.argv[1])" "$T/race-a"
wait "$P"; echo "mkdir binary exit status: $?"
cat "$T/mkdir.trace"

echo "== 2. control: python os.mkdir in the same window"
strace -f -o "$T/py.trace" -P "$T/race-b" \
  -e inject=mkdir,mkdirat:delay_enter=2000000 \
  python3 -c "import os,sys; os.mkdir(sys.argv[1])" "$T/race-b" 2>/dev/null &
P=$!
sleep 1.5; python3 -c "import os,sys; os.mkdir(sys.argv[1])" "$T/race-b"
wait "$P"; echo "python os.mkdir exit status: $?"
cat "$T/py.trace"

echo "== 3. control: bash set -C redirect (O_EXCL) in the same window"
strace -f -o "$T/sh.trace" -P "$T/race-c" -e inject=openat:delay_enter=2000000 \
  bash -c 'set -C; : > "$1"' _ "$T/race-c" 2>/dev/null &
P=$!
sleep 1.5; : > "$T/race-c"
wait "$P"; echo "bash O_EXCL exit status: $?"
cat "$T/sh.trace"
