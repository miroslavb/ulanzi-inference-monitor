# Repository operating notes

- This repository is the source of truth for the Ulanzi Inference Monitor plugin and its standalone `inf-agent`.
- Preserve the provider contract in `agent/README.md`: one `/providers` snapshot, `kind: limit|balance`, and per-provider failures isolated by the last-good cache.
- Provider probes may read local credentials but must never refresh, rewrite, or log secrets. OpenAI uses Codex's ChatGPT token read-only via `/root/.codex/auth.json`; Claude uses its OAuth credentials read-only.
- Hermes returning structured Nous account JSON with `logged_in:false` is a supported fallback state, not a fetch failure. Keep the retry backoff and do not reintroduce per-refresh `no json` log spam; malformed helper output and nonzero exits must remain visible.
- Keep the agent Python-stdlib-only. Add dependencies to the plugin only when the Ulanzi runtime actually requires them.
- The D200H SVG renderer does not reliably support `pathLength`; percentage rings must remain explicit arc paths.
- `providerIds` is an ordered allow-list: preserve its saved order when cycling. The shared Ulanzi PI CSS hides native checkboxes and requires each checkbox to be immediately followed by its `<label>` (`input + label`) for a visible state.
- After code changes run: `python3 test/test_agent.py -v`, `python3 -m py_compile agent/inf-agent.py`, `node --check` for changed JavaScript, `node test/render-openai.mjs`, `node test/render-limits.mjs`, `node test/settings.mjs`, `node test/provider-editor.mjs`, and `./pack.sh`.
- Before delivery, test `test/preview.mjs` against the deployed live agent, confirm `/providers` contains every expected provider (including Ollama Cloud and OpenCode Go when configured), and check `inf-agent.service` after restart.
- Keep `manifest.json`, `package.json`, `CHANGELOG.md`, release artifacts, and documentation versions in sync.
