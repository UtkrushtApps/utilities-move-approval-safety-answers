# Solution Steps

1. Keep the model boundary limited to interpreting customer intent. Do not let a `propose_close` decision directly invoke the irreversible tool.

2. Persist every valid initial closure proposal in `move_sessions` with the exact customer, account, stop date, revision, and `awaiting` state. Return a bounded confirmation prompt and make no service-state changes.

3. Validate account ownership before creating a pending proposal, and bind each session identifier to one customer so another customer cannot reuse durable workflow state.

4. Treat a confirmation as authorization only when a durable proposal exists, is in an eligible state, and every account or date extracted from the confirmation exactly matches the stored values. A confirmation with no extracted fields refers to the exact stored proposal.

5. Atomically transition an approval from `awaiting` to `executing`. Returning the claimed record only to the winning caller prevents overlapping requests in the same session from both crossing the tool boundary.

6. Use a global deterministic operation key derived from account and stop date. Reserve that key in `execution_claims` before invoking the tool so approvals arriving through different sessions also cannot produce duplicate effects.

7. Add unique constraints for tool calls and service orders as defense in depth. Execute the simulated external effect and service-order record in one SQLite transaction.

8. After successful execution, durably mark both the global operation and session proposal completed. Repeated approvals then return the same completed response without invoking the tool again.

9. Reconcile crash-window replays by checking for an already durable service order before attempting execution. If it exists, mark the session completed and return a replay-completed response.

10. For missing, mismatched, cancelled, currently executing, or otherwise unusable approvals, return a safe non-executing response. Release claims after definite tool rejection so a later explicit approval can retry safely.

11. Record bounded trace events for interpretation, pending proposal creation, approval acceptance or rejection, execution completion or failure, cancellation, and replay outcomes. Store identifiers and reason codes only—never raw customer messages or model free-form replies.

12. Run `python -m agent --selfcheck` and `python -m pytest -q invariants` to validate fixture loading and the initial, repeated, and overlapping approval guarantees.

