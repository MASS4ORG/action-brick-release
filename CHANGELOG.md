# Changelog

- Fixed: select stable CLI images and reuse recorded build digests for release retries.

- Added: reusable publish readiness workflow for scheduled and manual pre-tag checks with a read-only token MASS4ORG/action-brick-publish#1.
- Clarified: registry signing trust and namespace publisher registration are separate prerequisites.
- Fixed: forward environment signing and publishing secrets into reusable releases.
