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
    secrets:
      MASS4_BRICKS_CI_SIGNING_KEY: ${{ secrets.MASS4_BRICKS_CI_SIGNING_KEY }}
      MASS4_BRICKS_STORE_TOKEN: ${{ secrets.MASS4_BRICKS_STORE_TOKEN }}
    with:
      source-tests: Brick~/Tests/My.Brick.Tests/My.Brick.Tests.csproj
```

| Job            | Secrets | Does                                                                                                  |
|----------------|---------|-------------------------------------------------------------------------------------------------------|
| `image`        | none    | Resolves the pinned turian-cli version to its digest                                                  |
| `source-tests` | none    | Builds and runs the brick's tests against the Turian release of that CLI                              |
| `qualify`      | none    | Builds, consumer-tests and qualifies the archives, binding their bytes to the tag and commit          |
| `publish`      | yes     | In the `brick-production` environment: checks the bytes, signs and uploads; runs no brick code        |

The caller explicitly forwards the two secret names shown above. Their values stay in the calling repository's environment and are available to the `publish` job after its environment rules pass; the public key stays an environment variable. Keep `secrets: inherit` out of the caller. The workflow declares these names as optional for compatibility; signing and uploading require nonempty values.

The repository's `brick-production` environment holds `MASS4_BRICKS_CI_SIGNING_KEY` and `MASS4_BRICKS_STORE_TOKEN` as secrets and `MASS4_BRICKS_CI_PUBLIC_KEY` as a variable. Restrict it to `v*` tags, with a required reviewer and no administrator bypass.

Before the first tag, a Store administrator must authorize the CI public key in **both** registry signature trust and namespace publisher authority. Import it additively through `Registry:TrustedPublicKeys`/`--initialize` and verify its fingerprint in `/v1/keys`; separately register it under `org.mass4` at `/account/namespaces`. Neither step performs the other. Apply the same two checks to the Tier 1 key for emergency manual releases, with its private half remaining on the owner's workstation. Preserve existing registry keys unless a separate rotation/revocation is approved. Clients also need independent signing-key trust.

| Input            | Default                    | Description                                                                   |
|------------------|----------------------------|-------------------------------------------------------------------------------|
| `brick-path`     | `.`                        | Brick folder in the repository                                                |
| `precast`        | `true`                     | Compile assemblies before packing                                             |
| `twin`           | `true`                     | Release the baked twin beside the brick, a variant of its id and version      |
| `turian-version` |                            | Exact turian-cli version, e.g. `3.3.1`; empty for the one this workflow pins  |
| `source-tests`   |                            | Test project under the brick                                                  |
| `test-command`   |                            | Further tests on the runner; `BRICK_ARCHIVE` is the exact archive             |
| `store-url`      | `https://bricks.mass4.org` | Asset store to upload to                                                      |

### Publish readiness

The `publish` job runs [publish readiness](https://github.com/MASS4ORG/action-brick-publish#publish-readiness) before it signs: image pin, registry signature trust, namespace publisher authority, token namespace, the store's provenance read and curator advisories, each failure naming its layer. Run the same checks before tagging, on a schedule and by hand, with `.github/workflows/brick-readiness.yml`:

```yaml
name: Brick readiness

on:
  schedule:
    - cron: "17 6 * * *"
  workflow_dispatch:

permissions:
  contents: read

jobs:
  readiness:
    uses: MASS4ORG/action-brick-release/.github/workflows/readiness.yml@v1
    secrets:
      MASS4_BRICKS_STORE_TOKEN: ${{ secrets.MASS4_BRICKS_STORE_TOKEN }}
```

It checks the manifest's id and version against the CLI this workflow pins, reads only the publish token and the `MASS4_BRICKS_CI_PUBLIC_KEY` variable, and never requests the signing key. Its job selects the `environment` input, `brick-production` by default; a scheduled run comes from the default branch, so that environment's tag restriction and required reviewer apply to it. Take `brick-path`, `twin` and `store-url` as in a release.

### Re-running a tag

A release never resolves a moving tag: it uses the version this workflow pins, or an exact one the caller names, and turian-cli version tags are never pushed twice. So a re-run resolves the same digest, packs the same bytes, and the store accepts the identical upload again.

The store is the record of each release's provenance: the signed release JSON carries the image digest and Turian version as its unsigned `build`, and the store keeps the first `build` and source commit it received. Before uploading, the publish job reads that record back: it refuses different bytes, a re-run built by another image than the recorded one, and any build a curator advisory rejects. Identical bytes with other metadata are accepted, keep the first record and show up as warnings.

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
