# CI Workflow Improvements — `tests.yml` & Friends

Generated from audit of `.github/workflows/tests.yml`, `.github/workflows/*.yml`, `pytest.ini`, `.coveragerc`, `requirements*.txt`, `pyrightconfig.json`.

---

## 1. Workflow Duplication (HIGH)

Four jobs in `tests.yml` (lines 16–165) repeat the same **checkout → setup-python → system-deps → pip-install** preamble verbatim. Aggregate copy-paste:

| Block              | `test` (l.26–55) | `coverage` (l.66–87) | `typecheck` (l.109–130) | `compat` (l.141–162) |
|--------------------|:---:|:---:|:---:|:---:|
| Checkout           | ✓   | ✓   | ✓   | ✓   |
| Setup Python+cache | ✓   | ✓   | ✓   | ✓   |
| Linux apt deps     | ✓‡  | ✓   | ✓   | ✓   |
| pip install        | ✓*  | ✓   | ✓   | ✓   |

‡ `test` guards with `if: runner.os == 'Linux'`; the other three are ubuntu-only anyway.
* `test` splits install into two steps (Windows vs non-Windows); others are single step.

**38 lines** (the setup block) × 4 jobs = **152 lines of duplication** in a 165-line file.

**Recommendation: Composite action.** Extract the shared preamble into `.github/actions/setup/action.yml`:

```yaml
# .github/actions/setup/action.yml
name: 'Setup Jukebox'
description: 'Checkout, install Python, system deps, pip deps'
inputs:
  python-version:
    description: 'Python version'
    default: '3.12'
runs:
  using: 'composite'
  steps:
    - name: Checkout
      uses: actions/checkout@v6

    - name: Setup Python ${{ inputs.python-version }}
      uses: actions/setup-python@v6
      with:
        python-version: ${{ inputs.python-version }}
        cache: 'pip'
        cache-dependency-path: |
          requirements.txt
          requirements-test.txt
          ${{ runner.os == 'Windows' && 'requirements-windows.txt' || '' }}

    - name: Install Linux system dependencies
      if: runner.os == 'Linux'
      shell: bash
      run: |
        sudo apt-get update
        sudo apt-get install -y libasound2-dev libjack-dev libegl1

    - name: Install Python dependencies
      shell: bash
      run: |
        python -m pip install --upgrade pip
        if [ "$RUNNER_OS" = "Windows" ]; then
          python -m pip install -r requirements-windows.txt -r requirements-test.txt
        else
          python -m pip install -r requirements.txt -r requirements-test.txt
        fi
```

Then each job collapses to 6 lines (setup + run). This eliminates the triple OS-split step in `test` too.

---

## 2. Caching Gaps (HIGH)

### 2a. `cache-dependency-path` includes irrelevant files on non-Windows runners

In `typecheck` (line 117–119), `coverage` (line 74–76), and `compat` (line 149–151), `requirements-windows.txt` is listed in `cache-dependency-path` even though these jobs run on **ubuntu-latest** and never install from that file.

**Effect:** A PR modifying only `requirements-windows.txt` (e.g. bumping `pydirectinput`) invalidates the pip cache for all Ubuntu jobs, forcing a fresh `pip install`. Cache hit rate drops across the entire matrix for no reason.

**Fix:** Only include `requirements-windows.txt` in the cache key when `runner.os == 'Windows'`. With the composite action above, this is handled via conditional expression.

### 2b. No pyright cache

Pyright has a built-in persistent type-checking cache (`"pythonAnalysis.cache"` or CLI `--cache-dir`). The `typecheck` job (line 132–133) runs `python -m pyright` with no cache directory configured. This means every run re-analyzes the entire codebase from scratch (~10–20s on a PR).

**Fix:**

```yaml
- name: Run static type checks
  run: python -m pyright --cache-dir .pyright-cache
```

And add a cache step:

```yaml
- name: Cache pyright
  uses: actions/cache@v6
  with:
    path: .pyright-cache
    key: pyright-${{ hashFiles('pyrightconfig.json', '**/*.py') }}
    restore-keys: pyright-
```

### 2c. `build.yml` has no pip caching

In `.github/workflows/build.yml` line 39–43, `setup-python` is called without `cache: pip`. Each freeze build re-downloads all dependencies. Since builds run on tag pushes and workflow_dispatch, this is lower impact but still wasteful.

**Fix:** Add `cache: pip` and `cache-dependency-path` to the build job's setup-python step.

### 2d. CodeQL and Bandit workflows don't leverage pip cache

CodeQL (`.github/workflows/codeql.yml`) and Bandit (`.github/workflows/bandit.yml`) install packages via `pip` but don't enable setup-python caching. Bandit especially installs from scratch on every run. Neither needs much, but it's a trivial fix.

**Fix for bandit.yml line 31–34:**

```yaml
- name: Set up Python
  uses: actions/setup-python@v6
  with:
    python-version: '3.x'
    cache: 'pip'
- name: Install bandit
  run: |
    python -m pip install --upgrade pip
    pip install bandit[sarif]
```

---

## 3. Matrix Efficiency (MEDIUM)

### 3a. Coverage only on Ubuntu

The `coverage` job (line 60) runs only on `ubuntu-latest`. The `test` job runs the full suite on ubuntu, Windows, and macOS — but Windows/macOS runs never produce coverage data. This means coverage regressions that only manifest on non-Linux platforms are invisible until someone runs locally.

**Options:**

- **Fold coverage into the test matrix** as a boolean parameter `coverage: [true, false]`, limited to one OS:
  ```yaml
  test:
    strategy:
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
        include:
          - os: ubuntu-latest
            coverage: true
  ```
  Then in steps: `if: matrix.coverage` → add `--cov` flags and upload artifact. This eliminates the `coverage` job entirely, saving the duplication.

- **Run coverage on all three OSes** with a lower `--cov-fail-under` (or no fail) as a non-gating metric, keeping the strict gate only on ubuntu. This costs extra runner time but catches cross-platform coverage gaps.

### 3b. No test sharding

Each OS runner runs the entire test suite sequentially. With ~45 test files across 7 subdirectories, a single runner can take minutes. `pytest-xdist` could parallelize within a runner:

```yaml
- name: Run tests
  run: python -m pytest -q -n auto --durations=10
```

But on 2-core GitHub-hosted runners, `-n auto` gives limited benefit. More impactful: **semantic sharding** by test directory:

```yaml
strategy:
  matrix:
    os: [ubuntu-latest]
    shard: [tests/core, tests/analysis, tests/playback, tests/output, tests/ui, tests/native, tests/helpers]
```

This would require a coordinator step (or GitHub's `matrix` can't aggregate) — maybe overkill for this project size. Skippable now but worth noting.

---

## 4. Missing Safety Checks (LOW-MEDIUM)

### 4a. Security tools not integrated with test workflow

CodeQL and Bandit run as **independent workflows** triggered on push/PR, not as jobs within `tests.yml`. They:

- Don't share the pip cache (see 2d)
- Don't depend on or cascade from test results
- Run even when tests fail (wasted compute)
- Have separate concurrency groups — they could pile up

**Recommendation:** Move CodeQL and Bandit into `tests.yml` as additional jobs with `needs: test` so they only run after tests pass. Alternatively, keep them separate but add `concurrency` groups to prevent redundant runs on push+PR.

### 4b. `dependency-review-action` outdated

`.github/workflows/dependency-review.yml` line 33 uses `actions/dependency-review-action@v4`. Latest is **v5.0.0** (Node 24 runtime). Should bump.

---

## 5. Step Ordering / Optimization (MEDIUM)

### 5a. Linux system deps before pip install (correct)

The apt install step correctly precedes pip install — the audio libraries (`libasound2-dev`, `libjack-dev`) are build-time deps for `python-rtmidi`. This ordering is optimal.

### 5b. `pip install --upgrade pip` before installing deps (correct)

All jobs upgrade pip first. Good practice.

### 5c. OS-split install vs unified

Currently `test` uses two conditional pip steps (lines 45–55), while the other three ubuntu-only jobs use a single step. The composite action proposed in §1 merges them into one step with a shell conditional — less YAML, same behavior.

### 5d. `--durations=10` in test and compat, but not in coverage

The `coverage` job (line 95) does include `--durations=10`. Consistency is good here — but it uses `>` multiline syntax while `test` and `compat` use inline `run:`—minor style nit.

---

## 6. Tooling / Version Improvements

### 6a. Action version audit

| Action in use                 | Current Pin | Latest Available | Action Required |
|------------------------------|:-----------:|:----------------:|:---------------:|
| `actions/checkout`           | `@v6`       | `v6.0.3` (major) | ✅ Up to date   |
| `actions/setup-python`       | `@v6`       | `v6` (major)     | ✅ Up to date   |
| `actions/upload-artifact`    | `@v7`       | `v7` (major)     | ✅ Up to date   |
| `actions/download-artifact`  | `@v7`       | `v7` (major)     | ✅ Up to date   |
| `github/codeql-action/*`     | `@v4`       | `v4.36.2` (major)| ✅ Up to date   |
| `actions/dependency-review-action` | `@v4` | **`@v5`**      | ❌ **Bump to `@v5`** |
| `actions/stale`              | `@v10`      | **`@v11`**       | ❌ **Bump to `@v11`** |
| `actions/first-interaction`  | `@v3`       | `v3.0.0` (major)| ✅ Up to date   |

`@vN` major-version tags automatically receive patch updates, so `@v6` for checkout/setup-python is correct without pinning to `v6.0.3`.

### 6b. Missing `actions/cache` for pyright (see 2b)

### 6c. Dependabot configured, but GitHub Actions updates only monthly

`.github/dependabot.yml` line 16 sets `interval: "monthly"` for GitHub Actions. This is why `@v10` stale → `@v11` stale and `@v4` dependency-review → `@v5` haven't been auto-bumped. Consider changing to `"weekly"`.

---

## 7. Job Dependency Graph (MEDIUM)

Current: all 4 jobs in `tests.yml` run in parallel with no `needs:`.

| Job        | Depends On | Rationale |
|-----------|-----------|-----------|
| `test`     | —          | First gate |
| `coverage` | `test`     | No point checking coverage if tests fail |
| `typecheck`| —          | Independent; can run in parallel with `test` (catches typing issues regardless of test pass/fail) |
| `compat`   | `test`     | Testing Python 3.14 is wasted if 3.12 tests fail |

**Implementation:**

```yaml
jobs:
  test:
    …
  coverage:
    needs: test
    …
  typecheck:
    …
  compat:
    needs: test
    continue-on-error: true   # see §8
    …
```

This also means `coverage` and `compat` don't consume runner slots when `test` fails — important for private-repo minute budgets.

---

## 8. Python 3.14 Pre-Release — `compat` Job Risk Assessment (HIGH)

### Risks

1. **No stable PyQt6 wheels for 3.14:** PyQt6 wheels typically lag behind new CPython releases. If pip can't find a compatible wheel, the job hard-fails.

2. **`python-rtmidi` and `numpy` C extensions:** Both compile against CPython's C API. 3.14 is pre-release; ABI may have changed. Build failures are likely.

3. **`cache: pip` with "3.14":** `setup-python` may not find a pre-built 3.14 image; it will attempt to build from source, which is slow and may fail silently.

4. **`pydirectinput` (Windows-only, not in compat):** Irrelevant here since compat is ubuntu, but worth noting for any future Windows 3.14 job.

### Current mitigations in the workflow

- Job name is `compat` (communicates intent, not "required")
- `--cov-fail-under=100` is NOT used (good)
- Timeout is 20 min (reasonable)

### Missing mitigations

- **No `continue-on-error: true`** — if `compat` fails, the entire workflow check is red, blocking PR merges even when 3.12 tests pass. This is the #1 risk.
- **No `if: steps.setup.outcome == 'success'` guard** on the pyright/test steps — if Python 3.14 setup fails, subsequent steps get confusing errors.
- **No version-dependent cache key** — `compat` shares the same cache-key pattern as 3.12 jobs, risking cross-version cache poisoning.

### Recommended changes

```yaml
compat:
  needs: test
  continue-on-error: true    # don't block PRs on 3.14 failures
  runs-on: ubuntu-latest
  timeout-minutes: 20
  env:
    QT_QPA_PLATFORM: offscreen
  steps:
    - uses: actions/checkout@v6
    - uses: actions/setup-python@v6
      with:
        python-version: "3.14"
        cache: "pip"
        cache-dependency-path: |
          requirements.txt
          requirements-test.txt
          # Intentionally omit requirements-windows.txt — not used here
    - name: Install Linux system dependencies
      run: |
        sudo apt-get update
        sudo apt-get install -y libasound2-dev libjack-dev libegl1
    - name: Install Python dependencies
      run: |
        python -m pip install --upgrade pip
        python -m pip install -r requirements.txt -r requirements-test.txt
    - name: Run compatibility tests
      run: python -m pytest -q --durations=10
```

### Additional risk: Windows/macOS 3.14 gap

There is no Windows or macOS 3.14 compat job. If the project plans to release frozen builds for those platforms on 3.14 (see `build.yml` line 26 — it uses `python-version: '3.14'`), the compat gap is significant. The `build.yml` freezes on 3.14 but no CI verifies that the application actually runs on 3.14 outside Linux.

---

## 9. Concrete Suggested YAML Changes

### Priority order (impact × effort):

| # | Change | File | Lines | Effort |
|---|--------|------|-------|--------|
| 1 | Add `continue-on-error: true` to `compat` job | `tests.yml` | 135 | 1 line |
| 2 | Add `needs: test` to `coverage` and `compat` | `tests.yml` | 60, 135 | 2 lines |
| 3 | Bump `actions/dependency-review-action` `@v4` → `@v5` | `dependency-review.yml` | 33 | 1 char |
| 4 | Bump `actions/stale` `@v10` → `@v11` | `stale.yml` | 21 | 2 chars |
| 5 | Remove `requirements-windows.txt` from cache-dependency-path in ubuntu-only jobs | `tests.yml` | 74–76, 117–119, 149–151 | 3 lines |
| 6 | Fold `coverage` into `test` matrix (eliminate duplicate job) | `tests.yml` | 60–103 | ~40 lines removed |
| 7 | Create composite action for shared setup | new file + `tests.yml` | — | New file + edits |
| 8 | Add pyright caching | `tests.yml` | 132–133 | ~6 lines |
| 9 | Add pip caching to `build.yml` | `build.yml` | 39–43 | 2 lines |
| 10 | Change Dependabot GitHub Actions interval to weekly | `.github/dependabot.yml` | 16 | 1 word |

### Detailed edits for highest-priority items:

**Item 1 — `compat` continue-on-error (tests.yml line 135→136):**

```yaml
  compat:
    needs: test
    continue-on-error: true
    runs-on: ubuntu-latest
```

**Item 2 — `needs:` on coverage and compat:**

```yaml
  coverage:
    needs: test
    runs-on: ubuntu-latest
```

```yaml
  compat:
    needs: test
    continue-on-error: true
```

**Item 5 — Clean ubuntu-only cache-dependency-path:**

In `typecheck`, `coverage`, and `compat` jobs, replace:
```yaml
          cache-dependency-path: |
            requirements.txt
            requirements-windows.txt
            requirements-test.txt
```
with:
```yaml
          cache-dependency-path: |
            requirements.txt
            requirements-test.txt
```

**Item 9 — build.yml pip cache (lines 39–43):**

```yaml
      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: ${{ matrix['python-version'] }}
          cache: 'pip'
          cache-dependency-path: |
            requirements.txt
            requirements-windows.txt
```

---

## Summary

| Category | Issues Found | Priority |
|----------|-------------|----------|
| Duplication | 4 jobs × 38-line preamble; `test` and `coverage` nearly identical | HIGH |
| Caching | pip-cache key bloated by irrelevant OS files; no pyright cache; build.yml missing cache | HIGH |
| Matrix | Coverage not folded into matrix; no sharding; 3.14 only on ubuntu | MEDIUM |
| Safety | CodeQL/Bandit independent, no cache sharing, don't gate on tests | LOW |
| Step order | Correct as-is; composite action simplifies | LOW |
| Versions | 2 actions outdated; dependabot interval too conservative | LOW |
| Dep graph | Missing `needs:` wastes runner minutes on coverage/compat after test failure | MEDIUM |
| 3.14 risk | No `continue-on-error`; no Windows/macOS compat; possible wheel gaps | HIGH (blocking) |

**Immediate fixes** (5 min, high impact): `continue-on-error` on compat, `needs: test` on coverage+compat, bump dependency-review+stale versions.

**Short-term** (1–2 hours): Composite action to eliminate duplication, clean cache keys per OS, add pyright caching.

**Medium-term** (half-day): Fold coverage into test matrix, add pip cache to build.yml, integrate CodeQL/Bandit into main workflow.
