# Service portability and API parsing cleanup — October 9, 2026

The October 7 service watcher/reporting additions were pulled at `17c64ee`. On default Windows Python 3.12, the ordinary 169-test suite reported 13 errors: Unicode report writes failed under cp1252, watcher result events were then absent, and a source-symlink test required an unavailable privilege. Three representative failures passed with `-X utf8`, isolating the encoding dependency.

The cleanup makes service contract files, reports and proposed patch files explicitly UTF-8 with LF line endings. The baseline guard compares the host-owned contract's exact UTF-8 bytes, so malformed or changed README content returns `BASELINE_CHANGED` rather than an uncaught decoding exception. No authority, effect-gate, canonical format, model request, or permission policy changed.

The source redirect test now uses a real directory junction on Windows and a real file symlink on POSIX. It verifies that redirected source is refused, the external source remains unchanged, and an existing session's sentinel file is preserved. It needs no Windows file-symlink privilege and skips no checks.

The previously deferred provider-envelope issue is closed: duplicate JSON object keys at any depth are rejected, and explicitly noncompleted assistant messages cannot be accepted under an overall completed response. Omitted message status remains compatible with the existing optional metadata fixtures. Error messages do not echo key names or payload values. Model-generated decision JSON and function arguments still use their independent strict validation.

An independent review identified the malformed-contract error path. A new regression reproduced it before the guard changed to byte comparison. Other new regressions reproduced the default-encoding report failure, a Unicode candidate patch failure, duplicate provider keys, and contradictory message completion status before their fixes.

## Verification

The final validation uses default Windows Python without `-X utf8` or a locale override. It includes the complete ordinary suite and the three affected real Docker checks: healthy service control, regression investigation/candidate/receipt, and continuing watcher collection across good, bad and crashing source edits. The Docker checks use recorded tool choices or collector-only operation; no paid API calls are needed.

Results: all 174 ordinary tests passed, and all three affected Docker tests passed. No checks were skipped. The independent review's one Important finding was reproduced and corrected with a failing-then-passing regression; no deferred minor findings remain for this cleanup. POSIX execution was not rerun on this Windows machine.

## Starting the watcher here

The convenience script retains its existing macOS demo-repo default. On another computer, supply the path to your actual Git repository containing `src/clamp.py`:

```powershell
python scripts/watch_observed_service.py --repo 'C:\path\to\your-service-repo'
```

Docker must be running in Linux-container mode. The script prompts locally for a key when needed; session files remain under ignored `work/` paths.

## Next step

The Authority primitive already represents an exact-action permission grant or denial, and the gate checks issuer, subject, resource, expiry and revocation. The example client currently grants a simulated permission automatically after both test suites pass. The next workflow should keep a verified proposal durably awaiting a separate trusted operator or policy decision, then issue its scoped Authority and recheck freshness at the gate. Real patch application remains a later effect integration.
