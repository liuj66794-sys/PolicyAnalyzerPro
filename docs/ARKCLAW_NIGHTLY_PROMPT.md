# ArkClaw Nightly Scheduled Prompt

The content below is intended to be pasted directly into an ArkClaw scheduled task.

---

Working directory: `D:\chapter1`

Objective: act as the nightly validation agent for PolicyAnalyzerPro. Run one full P0 verification cycle, then produce a concise handoff summary for the next working session. Do not drift into unrelated exploration.

Hard rules:

1. Do not modify business code, tests, or config files unless the task explicitly asks for repair.
2. This run is for **verification and reporting**, not feature work.
3. If a failure occurs, preserve the scene and summarize the first blocking problem instead of looping indefinitely.
4. Do not delete user files or clean unrelated workspace contents.
5. If the git worktree is dirty, keep validating but do not revert anything.

Execution order:

1. Go to `D:\chapter1`.
2. Record `git status --short`.
3. Run source-side P0 validation:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File D:\chapter1\scripts\run_p0_acceptance.ps1 -Python D:\chapter1\.venv\Scripts\python.exe -SkipBuild
```

4. If step 3 passes, run packaged-app validation:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File D:\chapter1\scripts\validate_dist.ps1 -Python D:\chapter1\.venv\Scripts\python.exe -Build
```

5. Check whether these artifacts exist:
   - `D:\chapter1\tmp\ocr_acceptance\ocr_acceptance_report.json`
   - `D:\chapter1\tmp\ocr_acceptance\ocr_output_utf8.txt`
   - `D:\chapter1\tmp\startup-self-check.json`
   - `D:\chapter1\dist\PolicyAnalyzerPro\startup-self-check.json`

6. Produce the final summary.

Required output format:

- `Conclusion`
  - only one of: `Pass`, `Partial Pass`, `Fail`
- `Commands Run`
  - list the actual commands executed
- `Result Summary`
  - whether unit/regression tests passed
  - whether OCR end-to-end acceptance passed
  - whether packaging succeeded
  - whether packaged self-check passed
- `Blocking Issues`
  - only real delivery blockers
  - write `None` if there are no blockers
- `Recommended Human Follow-Up`
  - at most 3 items, sorted by priority
- `Artifact Paths`
  - list the generated reports and logs with full paths

Decision rules:

- If `run_p0_acceptance.ps1 -SkipBuild` fails, the result must be `Fail`.
- If source-side P0 passes but `validate_dist.ps1 -Build` fails, the result must be `Partial Pass`.
- Only mark `Pass` when tests, OCR, packaging, and packaged self-check all pass.
- If packaged self-check fails, never mark the run as `Pass`.

Extra reporting rules:

- On failure, identify the first blocking error and the most likely file or module involved.
- On success, explicitly say that no code was auto-modified during the run and only validation was performed.
- Do not write vague conclusions; reference real command results and artifact paths.
