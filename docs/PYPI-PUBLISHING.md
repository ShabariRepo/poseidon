# Publishing Poseidon to PyPI

Two ways to publish `poseidon-ai`: **token upload** (what we're doing now, manual) and **trusted publishing** (the automated CI path, set up once). Both end with `pipx install poseidon-ai` working for everyone.

---

## A. Token upload (manual, immediate)

We already have a PyPI API token in `~/.pypirc` (`[pypi]`, `username = __token__`). To publish the current build:

```bash
cd ~/Desktop/code/poseidon
rm -rf dist && python3 -m build           # fresh wheel + sdist for the current version
./.venv/bin/twine check dist/*            # metadata/README sanity
./.venv/bin/twine upload dist/*           # uses ~/.pypirc token
```

Notes:
- **A version can only be uploaded once** — bump `version` in `pyproject.toml` + `poseidon/__init__.py` before re-publishing.
- `twine check` catches a bad long-description/README before the irreversible upload.
- After it lands: `pipx install poseidon-ai` (or `pip install poseidon-ai`) works anywhere.

---

## B. Trusted publishing (automated, set up once — recommended going forward)

Trusted publishing lets `release.yml` publish on a version tag **with no token stored in GitHub** — PyPI trusts the specific repo+workflow via OpenID Connect. This is the durable setup.

### One-time click-path on pypi.org
1. Log in to **pypi.org** with the Bonito account.
2. Because `poseidon-ai` **already exists** after the first token upload (section A), go to it directly: **Your projects → `poseidon-ai` → Manage → Publishing** (left sidebar).
   - *(If publishing for the very first time via CI instead of a token, use **Account → Publishing → Add a pending publisher** instead — same fields.)*
3. Under **"Add a new trusted publisher" → GitHub**, fill in exactly:
   - **PyPI Project Name:** `poseidon-ai`
   - **Owner:** `ShabariRepo`
   - **Repository name:** `poseidon`
   - **Workflow name:** `release.yml`
   - **Environment name:** `pypi`  ← must match `environment: pypi` in the `publish-pypi` job
4. Click **Add**. Done — no token needed after this.

### GitHub side (one-time)
1. Repo → **Settings → Environments → New environment** → name it **`pypi`** (matches the workflow). (Optional: add a required reviewer so publishes need a click.)
2. `release.yml` already has `permissions: id-token: write` and the `publish-pypi` job uses `pypa/gh-action-pypi-publish` — no changes needed.

### Then, to release
```bash
# bump version in pyproject.toml + poseidon/__init__.py first
git tag v0.14.0 && git push --tags
```
That triggers `release.yml`:
- builds wheel + sdist → **publishes to PyPI** (via trusted publishing, no token),
- builds standalone binaries (Mac arm64/x86, Windows, Linux) → attaches to the GitHub Release.

---

## Recommended order
1. **Now:** do **A** (token upload) — instant, makes `pip install poseidon-ai` work today.
2. **Once:** do **B** (trusted publishing) so every future `git tag vX.Y.Z && git push --tags` auto-publishes with no token in CI.
3. Host the install one-liners (`install.sh` / `install.ps1`) on getbonito.com/poseidon (see `DISTRIBUTION.md`).
