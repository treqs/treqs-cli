# Publishing `treqs-cli`

`treqs-cli` publishes one universal Python wheel and one source distribution.
The release flow mirrors `roar-cli` where the packages have the same needs:

1. Build and validate immutable distribution artifacts in a checkout job.
2. Install the built wheel in an isolated environment and exercise the `treqs`
   console script.
3. Pass only the validated artifacts to a separate environment-gated upload job.
4. Validate on TestPyPI before publishing a matching GitHub release to PyPI.

Unlike `roar-cli`, this package contains no native code, so it does not need
platform-specific wheel or Rust build matrices.

## One-time repository setup

Before the first release:

- Confirm the `treqs-cli` project name is available on both
  [TestPyPI](https://test.pypi.org/) and [PyPI](https://pypi.org/).
- Decide and add the package license. Do not publish until the repository and
  `pyproject.toml` carry the intended license metadata.
- Add a `testpypi` GitHub environment with a `TEST_PYPI_API_TOKEN` Actions
  secret. The first upload needs an account token that may create a project;
  replace it with a project-scoped token after the project exists.
- Add a `pypi` GitHub environment with a `PYPI_API_TOKEN` Actions secret. The
  first upload needs an account token that may create a project; replace it
  with a project-scoped token after the project exists.
- Add required reviewers to the environments if release approval is desired.

The upload jobs use `__token__` authentication. Keep the secrets in their
matching environments rather than as unprotected repository-wide secrets.

## Build and validate locally

Run from the repository root:

```bash
rm -rf dist
uv build
uvx twine check dist/*
```

Verify that `dist/` contains only:

- `treqs_cli-<version>-py3-none-any.whl`
- `treqs_cli-<version>.tar.gz`

Install the wheel into a clean environment rather than importing the working
tree:

```bash
python -m venv /tmp/treqs-cli-release-check
/tmp/treqs-cli-release-check/bin/pip install dist/*.whl
cd /tmp
/tmp/treqs-cli-release-check/bin/treqs --version
/tmp/treqs-cli-release-check/bin/treqs --help
```

## Validate with TestPyPI

1. Set a unique version in both `pyproject.toml` and
   `src/treqs_cli/__init__.py`. TestPyPI does not allow replacing files for an
   existing version.
2. Run the **Publish to TestPyPI** workflow from the candidate branch with
   `dry_run` left enabled.
3. Download and inspect the `distributions` workflow artifact.
4. Run the workflow again with `dry_run` disabled to upload the same package
   version to TestPyPI.
5. Verify installation:

```bash
uv tool install \
  --index https://pypi.org/simple/ \
  --default-index https://test.pypi.org/simple/ \
  treqs-cli==<version>
treqs --version
treqs --help
```

## Publish to production PyPI

Production uploads occur only for a published GitHub release. A manual run of
the **Publish to PyPI** workflow builds and validates artifacts but cannot
upload them.

1. Confirm tests, lint, type checks, and the TestPyPI install pass.
2. Confirm `pyproject.toml` and `src/treqs_cli/__init__.py` have the same final
   version.
3. Merge the release commit to `main`.
4. Create and publish a GitHub release whose tag is exactly `v<version>` (for
   example, `v0.1.0`).
5. The workflow verifies the tag against `pyproject.toml`, rebuilds and smoke
   tests the package, uploads it to PyPI through the `pypi` environment, and
   attaches the wheel and sdist to the GitHub release.
6. Verify the public install in a fresh tool environment:

```bash
uv tool install treqs-cli==<version>
treqs --version
treqs --help
```

## Rollback

PyPI and TestPyPI do not allow overwriting an existing distribution file. If a
release is bad, yank it in the package index, fix the issue, increment the patch
version, and publish a new release. Deleting a release can break pinned users
and should be reserved for exceptional cases.
