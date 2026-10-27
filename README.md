# Brick workflows

Verify a brick on pushes and pull requests with no setup:

```yaml
name: Verify brick
on: {push: {branches: [main]}, pull_request: {}}
permissions: {contents: read}
jobs:
  verify:
    uses: MASS4ORG/brick-workflows/.github/workflows/verify.yml@v1
```

## Which setup do I need?

| You want | Setup |
|---|---|
| Verify on push/PR only | None: zero secrets, zero environments |
| Publish to the MASS4 store | `brick-production` environment restricted to `v*` tags, two secrets, and store-side key registration |
| Publish to your own registry | `brick-action-build` only, no secrets; upload its archives through your registry's own pipeline |

## Release to the MASS4 store

Create `.github/workflows/brick-release.yml`:

```yaml
name: Release brick
on:
  push:
    tags: ["v*"]
permissions:
  contents: read
jobs:
  release:
    uses: MASS4ORG/brick-workflows/.github/workflows/release.yml@v1
    secrets:
      BRICKS_SIGNING_KEY: ${{ secrets.BRICKS_SIGNING_KEY }}
      BRICKS_STORE_ACCESS_TOKEN: ${{ secrets.BRICKS_STORE_ACCESS_TOKEN }}
```

The signing key must already be registered with the store for your package namespace. The store token must grant `registry.publish` for that namespace. Use an unencrypted OpenSSH Ed25519 private key dedicated to CI; the action derives its public key at run time. No GitHub variable is needed.

Create the environment and its two secrets from your terminal, replacing `OWNER/BRICK` and the private-key file path:

```bash
repo=OWNER/BRICK
gh api --method PUT "repos/$repo/environments/brick-production" --input - <<'JSON'
{"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}
JSON
gh api --method POST "repos/$repo/environments/brick-production/deployment-branch-policies" -f name='v*' -f type=tag
gh secret set BRICKS_SIGNING_KEY --repo "$repo" --env brick-production < path/to/ci-private-key
gh secret set BRICKS_STORE_ACCESS_TOKEN --repo "$repo" --env brick-production
```

Keep the environment free of required reviewers. Pushing a release tag is the release decision; the workflow requires no approval clicks afterward. Store-side package approval, where applicable, is separate from GitHub execution.

Push a tag shaped `v<semver>` to release. Its version is injected into the packed manifest. A different `package.json` version produces a warning and does not block the release; that field remains useful during development. A normal branch push never publishes a release.

## What runs

The release planner reads package identity and store provenance without executing brick code. For a first publication it selects the highest stable semver CLI image tag; an exact `turian-version` overrides that choice. It never uses Docker's `latest` tag.

When the store already has the release, including an unapproved or partially published release, its recorded CLI digest takes precedence. Source tests, packing, consumer qualification and publishing use that same selected image/version. The selection is recorded in the job summary and `build.json` beside the archives. Existing receipts without usable build provenance fail explicitly instead of guessing another build image.

When an existing archive is readable, the planner verifies its recorded SHA256 and replays those exact bytes through qualification and consumer tests. Missing variants are built normally. Pending archives may be hidden by the store: those variants rebuild with the recorded CLI and must match the receipt's archive hash. A nondeterministic older CLI can still fail that hash check; the workflow never overwrites the immutable stored archive.

Build and test jobs have no publishing credentials. The isolated planner reads the namespace token, and the isolated publish job derives the key identity, runs authenticated readiness, signs and uploads the qualified bytes. Publish rechecks the store record immediately before upload. CLI version tags remain immutable.

Verification uses the same highest-stable-semver resolver and defaults source tests to that CLI's release sources. `turian-ref` is an optional development override for verify only.

## Inputs

| Input | Default | Purpose |
|---|---|---|
| `brick-path` | `.` | Brick folder in the caller repository |
| `precast` | `true` | Compile runtime assemblies before packing |
| `twin` | `true` | Build and release the baked variant alongside the source |
| `turian-version` | Empty | Resolve highest stable semver at tag time; an exact version overrides first-publication selection |
| `source-tests` | Empty | Test-project path under the brick |
| `source-test-dependency` | `{}` | Optional companion checkout JSON: `repository`, immutable `ref`, and `path` under `Bricks/` |
| `turian-ref` | Empty | Verify-only source override; otherwise use the selected CLI release |
| `test-command` | Empty | Release-only additional archive tests; `BRICK_ARCHIVE` names the source archive |
| `store-url` | `https://bricks.mass4.org` | Release destination and provenance source |

Declare `source-tests` in both callers when tests exist. A Bepu caller also supplies its companion source checkout:

```yaml
    with:
      source-tests: Brick~/Tests/Turian.Physics.Bepu.Tests/Turian.Physics.Bepu.Tests.csproj
      source-test-dependency: >-
        {"repository":"MASS4ORG/org.mass4.turian.physics","ref":"v1.0.0","path":"org.mass4.turian.physics"}
```

Companion checkouts supply producer projects for source tests. Consumer qualification resolves declared package dependencies from the store, so publish dependencies before their dependents.

## Manual preflight

Run `readiness.yml` manually in this repository with a package id and prospective version. It uses no secrets or environment. An optional public-key input enables registry-trust and namespace-publisher checks; omitted identity checks are reported as skipped. Token and private provenance checks are also skipped and explicitly deferred to tag-time preflight. A successful manual run means the public checks passed, not that authenticated publication is fully ready.

## Troubleshooting

| Failure layer | Fix |
|---|---|
| Image selection | Confirm an exact stable CLI image exists, or remove the override to resolve the highest stable semver |
| Package/tag | Push a `v<semver>` tag; manifest-version drift is only a warning |
| Signing identity | Supply an unencrypted OpenSSH Ed25519 CI key |
| Registry trust | Ask the registry operator to authorize the derived public key in signature trust |
| Namespace publisher | Register that public key as a publisher for the package namespace |
| Token/account: 401 | Replace an expired, revoked or wrong-store access token |
| Token/account: 403 or wrong namespace | Grant the token `registry.publish` for the package namespace |
| Provenance | Reuse the recorded build; investigate missing provenance or conflicting source/twin receipts |
| Changed archive bytes | Restore the original source/dependency inputs for a retry, or release a new package version |
| Advisories | Follow the linked advisory and resolve its stated restriction |
| HTTP 429/5xx or transport | Retry when the registry/store is healthy; check the configured store URL |

## Versions

`@v1` follows compatible implementation updates. Breaking input changes use a new major version. Turian releases do not require a new workflow release; CLI selection is independent of workflow versioning.
