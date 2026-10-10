#!/usr/bin/env bash
# Crush provider-bench lane driver. Usage: run_lane.sh <lane> [timeout_s]
# Runs T1 (fizzbuzz+pytest), T2 (surgical edit), T3 (MCP) in the lane dir,
# times each crush run, verifies independently, emits a results summary.
set -u
LANE="$1"
TIMEOUT="${2:-420}"
MODEL_ARG="${3:-}"
BENCH=/tmp/crush-bench-mn01
DIR="$BENCH/lanes/$LANE"
CRUSH="$HOME/.local/bin/crush"
MARKER="CRUSH-BENCH-MARKER-7734"

# env: openrouter key + working gemini key (ada-pi-pwa.env LAST so its
# GEMINI_API_KEY overrides the dead one in gemini-api-key.env — never sourced)
set -a
. "$HOME/.config/secrets/openrouter.env" 2>/dev/null
. "$HOME/.config/secrets/ada-pi-pwa.env" 2>/dev/null
set +a

cd "$DIR" || exit 1
printf 'CRUSH-BENCH-MARKER-7734 handle=mn01 lane=%s\n' "$LANE" > bench_marker.txt

P1='In the current directory, create fizzbuzz.py with a function fizzbuzz(n) that returns "FizzBuzz" when n is divisible by 15, "Fizz" when divisible by 3, "Buzz" when divisible by 5, otherwise str(n); and a main() that prints fizzbuzz for 1..15. Also create test_fizzbuzz.py with exactly 4 pytest tests covering: a multiple of 3, a multiple of 5, a multiple of 15, and a plain number. Then run python3 -m pytest -q and tell me how many tests passed.'
P2='Edit the existing fizzbuzz.py so that main() reads the upper bound from sys.argv[1] (default 15 when absent) and exits with an error message if the value is not a positive integer <= 100. Add one new test to test_fizzbuzz.py covering the bound check through main(). Then run python3 -m pytest -q and report the result.'
P3='An MCP server named bench-ro is configured in this project with tools lab_list and lab_read. Use lab_list to list the files here, then use lab_read to read bench_marker.txt. Reply with the exact contents of bench_marker.txt.'

run_task() {
  local name="$1" prompt="$2"
  local t0 t1 rc
  t0=$(date +%s%3N)
  if [ -n "$MODEL_ARG" ]; then
    timeout "$TIMEOUT" "$CRUSH" run -c "$DIR" -m "$MODEL_ARG" "$prompt" > "$DIR/${name}.out" 2> "$DIR/${name}.err"
  else
    timeout "$TIMEOUT" "$CRUSH" run -c "$DIR" "$prompt" > "$DIR/${name}.out" 2> "$DIR/${name}.err"
  fi
  rc=$?
  t1=$(date +%s%3N)
  echo "$((t1 - t0))" > "$DIR/${name}.ms"
  echo "$rc" > "$DIR/${name}.rc"
  echo "[$LANE/$name] rc=$rc wall=$((t1 - t0))ms"
}

pytest_count() {
  (cd "$DIR" && python3 -m pytest -q 2>/dev/null | tail -1)
}

echo "=== lane $LANE ==="
run_task task1 "$P1"
echo "  verify-t1: $(pytest_count)"

# task2 needs an existing fizzbuzz.py; seed canonical pair if T1 failed to leave one
if [ ! -f "$DIR/fizzbuzz.py" ]; then
  echo "  (seeding canonical fizzbuzz.py+test for T2 — T1 produced none)"
  cat > "$DIR/fizzbuzz.py" <<'EOF'
def fizzbuzz(n):
    if n % 15 == 0:
        return "FizzBuzz"
    if n % 3 == 0:
        return "Fizz"
    if n % 5 == 0:
        return "Buzz"
    return str(n)

def main():
    for i in range(1, 16):
        print(fizzbuzz(i))

if __name__ == "__main__":
    main()
EOF
  cat > "$DIR/test_fizzbuzz.py" <<'EOF'
from fizzbuzz import fizzbuzz

def test_fizz():
    assert fizzbuzz(3) == "Fizz"
    assert fizzbuzz(9) == "Fizz"

def test_buzz():
    assert fizzbuzz(5) == "Buzz"
    assert fizzbuzz(20) == "Buzz"

def test_fizzbuzz():
    assert fizzbuzz(15) == "FizzBuzz"
    assert fizzbuzz(30) == "FizzBuzz"

def test_plain():
    assert fizzbuzz(1) == "1"
    assert fizzbuzz(7) == "7"
EOF
fi

run_task task2 "$P2"
echo "  verify-t2: $(pytest_count)"

run_task task3 "$P3"
if grep -q "$MARKER" "$DIR/task3.out" 2>/dev/null; then
  echo "  verify-t3: marker found in agent reply"
else
  echo "  verify-t3: MARKER NOT in reply"
fi

echo "=== $LANE done ==="
