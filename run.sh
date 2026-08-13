#!/usr/bin/env bash
set -u
cd /root/task
python -m pip install -q -r requirements.txt

python -m agent --selfcheck
selfcheck_status=$?
if [ "$selfcheck_status" -ne 0 ]; then
  exit "$selfcheck_status"
fi

set +e
python -m pytest -q invariants
pytest_status=$?
set -e

if [ "$pytest_status" -ge 2 ]; then
  echo "Invariant suite could not be collected or executed"
  exit "$pytest_status"
fi

if [ "$pytest_status" -eq 1 ]; then
  echo "Invariant suite executed; business failures are expected before repair"
else
  echo "Invariant suite passed"
fi

echo "Agent scaffold ready"
