# Turian brick release workflows

Reusable workflows that release a [Turian](https://github.com/MASS4ORG/Turian) brick to the MASS4 asset store from a tag, and verify it on every push. They wire [action-brick-build](https://github.com/MASS4ORG/action-brick-build) and [action-brick-publish](https://github.com/MASS4ORG/action-brick-publish) so that brick code never runs where the publishing secrets are.

## Release

`.github/workflows/brick-release.yml` in the brick repository:

```yaml
name: Release brick

on:
  push:
    tags: ["v*"]

permissions:
  contents: read

jobs:
  release:
    uses: MASS4ORG/action-brick-release/.github/workflows/release.yml@v1
    with:
      source-tests: Brick~/Tests/My.Brick.Tests/My.Brick.Tests.csproj
```

| Job            | Secrets | Does                                                                                                  |
|----------------|---------|-------------------------------------------------------------------------------------------------------|
| `image`        | none    | Resolves the pinned turian-cli version to its digest                                                  |
| `source-tests` | none    | Builds and runs the brick's tests against the Turian release of that CLI                              |
| `qualify`      | none    | Builds, consumer-tests and qualifies the archives, binding their bytes to the tag and commit          |
| `publish`      | yes     | In the `brick-production` environment: checks the bytes, signs and uploads; runs no brick code        |

The repository's `brick-production` environment holds `MASS4_BRICKS_CI_SIGNING_KEY` and `MASS4_BRICKS_STORE_TOKEN` as secrets and `MASS4_BRICKS_CI_PUBLIC_KEY` as a variable. Restrict it to `v*` tags, with a required reviewer and no administrator bypass.

| Input            | Default                    | Description                                                                   |
|------------------|----------------------------|-------------------------------------------------------------------------------|
| `brick-path`     | `.`                        | Brick folder in the repository                                                |
| `precast`        | `true`                     | Compile assemblies before packing                                             |
| `twin`           | `true`                     | Release the baked twin `<id>.bake` beside the brick                           |
| `turian-version` |                            | Exact turian-cli version, e.g. `3.3.1`; empty for the one this workflow pins  |
| `source-tests`   |                            | Test project under the brick                                                  |
| `test-command`   |                            | Further tests on the runner; `BRICK_ARCHIVE` is the exact archive             |
| `store-url`      | `https://bricks.mass4.org` | Asset store to upload to                                                      |

### Re-running a tag

A release never resolves a moving tag: it uses the version this workflow pins, or an exact one the caller names, and turian-cli version tags are never pushed twice. So a re-run resolves the same digest, packs the same bytes, and the store accepts the identical upload again. The `brick-release-provenance` artifact records the digest, archive hashes and signed metadata.

## Verify

`.github/workflows/brick.yml` in the brick repository:

```yaml
jobs:
  brick:
    uses: MASS4ORG/action-brick-release/.github/workflows/verify.yml@v1
    with:
      source-tests: Brick~/Tests/My.Brick.Tests/My.Brick.Tests.csproj
```

It packs with the same pinned CLI as a release and runs the source tests against Turian's `main` (`turian-ref`). It takes the same `brick-path`, `precast`, `twin`, `turian-version` and `source-tests` inputs.

## Versions

`@v1` moves with every compatible release. A new pinned turian-cli is a minor release; only a breaking input change makes a `v2`.

## License

[MIT](LICENSE.md)
