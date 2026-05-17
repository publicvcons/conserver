# tests

`run_testplan.py` — automated runner for the Phase 0 acceptance plan
(`TEST_PLAN.md` in the workspace root), cases T1–T10.

```
cd seed/site && python3 -m http.server 8096 &   # for T10
~/venvs/tools/bin/python seed/conserver/tests/run_testplan.py
```

Exit 0 = all automatable checks pass; non-zero lists failures. Paths are
derived from the file's location; override with `PVCONS_WS`,
`PVCONS_SRCMP4`, `PVCONS_SITE`.

T6 includes a negative control (tampers a receipt signature and confirms
the verifier reports `BAD`). T7 and T10 have manual parts the runner
**cannot** cover — listening to source audio against the transcript, and
visually rendering the viewer + click-to-seek — these are reported as
"manual" and must still be done by a human.
