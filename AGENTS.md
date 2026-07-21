# Repository operating notes

- This repository is the source of truth for the Ulanzi Inference Monitor plugin and its standalone `inf-agent`.
- Preserve the provider contract in `agent/README.md`: one `/providers` snapshot, `kind: limit|balance`, and per-provider failures isolated by the last-good cache.
- Provider probes may read local credentials but must never refresh, rewrite, or log secrets. OpenAI uses Codex's ChatGPT token read-only via `/root/.codex/auth.json`; Claude uses its OAuth credentials read-only.
- Keep the agent Python-stdlib-only. Add dependencies to the plugin only when the Ulanzi runtime actually requires them.
- The D200H SVG renderer does not reliably support `pathLength`; percentage rings must remain explicit arc paths.
- After code changes run: `python3 test/test_agent.py -v`, `python3 -m py_compile agent/inf-agent.py`, `node --check` for changed JavaScript, `node test/render-openai.mjs`, and `./pack.sh`.
- Before delivery, test `test/preview.mjs` against the deployed live agent, confirm `/providers` contains every expected provider, and check `inf-agent.service` after restart.
- Keep `manifest.json`, `package.json`, `CHANGELOG.md`, release artifacts, and documentation versions in sync.
