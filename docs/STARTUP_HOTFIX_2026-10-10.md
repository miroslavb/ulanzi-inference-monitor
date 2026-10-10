# Startup hotfix v1.5.2 — partial acceptance, 2026-10-10

## Observed fault

Owner report: «монитора инференсов в ulanzi studio не получает данных пока не зайдешь в программу и не поставишь курсор на URL агента». [Source: User, 2026-10-10]

The installed Windows v1.5.1 source matched repository HEAD `309c030d8b8bf8b215337e851f8bf56040d37cee`. Studio 3.3.9 ran the plugin directly from its installed plugin directory. Saved profiles contained a Provider Switch URL pointing to `100.110.137.47:9890` and a Provider Tile URL pointing to `127.0.0.1:9890`. The previous main service applied whichever non-empty action URL arrived last. [Source: read-only Windows process/profile inspection and local source, 2026-10-10]

## Implemented change

A configured Provider Switch owns the shared sampler endpoint; a restored tile's localhost URL cannot override it. Standalone tiles retain their own URL support. `didReceiveSettings` prefers `settings` over an empty `param`. No profile, provider credential or remote-agent code was changed. [Source: working-tree `plugin/app.js` diff, 2026-10-10]

## Software evidence

- The fresh-process startup regression failed before the fix because the tile overwrote the persisted URL with localhost. After the priority fix, a separate cold-start case failed because `param:{}` hid the `settings` reply. Both cases passed after their respective fixes. [Source: `node test/startup.mjs` execution, 2026-10-10]
- All four startup scenarios passed through the real app and bundled SDK, with real WebSocket/HTTP fixture servers and without Property Inspector events. Existing renderer, settings and provider-editor checks passed. [Source: local Node test output, 2026-10-10]
- Ten agent unit tests passed with `INF_HERMES_ENV=/dev/null`, isolating fixtures from personal credential discovery. The first non-isolated run failed because the real Hermes environment took precedence over fixture credentials; that failure is retained as a test-environment issue, not an agent-code regression. [Source: Python test output, 2026-10-10]
- `pack.sh` produced plugin and agent v1.5.2 ZIPs; the agent source was unchanged. `git diff --check` passed. [Source: local build/diff output, 2026-10-10]
- The live preview reached the agent and found six provider records. Its full result was NOT green: the Ollama Cloud live-limits assertion failed, while its error tile rendered. This is separate from plugin endpoint ownership. [Source: live `test/preview.mjs`, 2026-10-10]

## Installed Windows evidence — 18:02 UTC

Private backup: `/home/worker/backups/infmonitor-20261010-startup` on `windows-worker` (WSL), outside the Studio Plugins tree. The installer backed up the plugin and affected profile manifests with private permissions before updating only `manifest.json`, `package.json`, `package-lock.json` and `plugin/app.js`. It preserved profiles and `.agent-url.json`. [Source: target installer/read-back receipt, 2026-10-10]

Installed v1.5.2 main-service SHA-256: `35d6e4eaf0f2a73cfcd3326b9d0fd2eab4524bab25364aa6c57ff6e6a076b137`. Read-back confirmed the installed version and retained agent host `100.110.137.47`. [Source: target file read-back, 2026-10-10]

Studio was fully restarted in minimized mode without URL/input interaction: new Studio PID `3688`, new inference plugin PID `33608`. A bounded TCP SYN capture observed post-restart connections from Windows to the correct agent at `18:02:53` and `18:02:58` UTC. This establishes resumed connection attempts; it does NOT prove HTTP status, current provider values or the physical panel display. [Source: guarded Windows process restart and 28-second `tailscale0` capture, 2026-10-10]

## Current outcome — final software and live HTTP checks passed

The owner renewed the request («Повтори запрос»). The exact previously rejected final-verification command was approved and executed successfully: four real-process startup scenarios, settings/editor tests, ten isolated agent tests, installer syntax and archive/source parity passed. The temporary verifier was removed and the app hash remained `35d6e4eaf0f2a73cfcd3326b9d0fd2eab4524bab25364aa6c57ff6e6a076b137`. Renderer checks and Python compilation also passed. Independent read-only review approved the same hotfix without material defects. [Source: renewed owner request, approval and fresh terminal test output; completed deleg_841fcb39 review, 2026-10-10]

A passive bounded HTTP capture at `19:11:44.906638..19:12:04.935472 UTC` contained five Windows `GET /providers` requests and five matching HTTP 200 response starts on their respective client ports. Only transport/status metadata was printed, never account values. The first capture-file attempt failed because tcpdump dropped privileges and could not open a path under `/root`; the successful attempt wrote through a private shell-opened stdout file descriptor. The 23-second capture ended with timeout status 124 as intended. The same Studio PID `3688` and inference PID `33608` remained alive, and installed file/hash/retained-host read-back matched v1.5.2. No URL/input interaction was made during this check. [Source: passive packet capture/parser and fresh Windows file/process read-back, 2026-10-10]

This verifies the software startup/polling repair and live HTTP responses, not the appearance of the physical panel. The separate Ollama Cloud live-limits preview failure was not fixed in this task. Existing profiles and the private backup were preserved. v1.5.2 GitHub release assets were not published; source publication is verified separately against the resulting Git commit and does not imply archive publication. [Source: bounded task scope, source tree and release state, 2026-10-10]

## Earlier approval blockers — historical, 2026-10-10

Earlier, the additional ad-hoc final verification command did not run because its approval request expired. It was retried only after the owner's renewed request and approval, as recorded above. Two separate attempts to update protected `AGENTS.md` also timed out without consent; that file remains unchanged and its denied write was not bypassed. [Source: prior approval-denial receipts; later owner-authorized final verification, 2026-10-10]
