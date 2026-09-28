# 18: Release pipeline

**What to build:** Tagging a release publishes a versioned public image to GHCR that runs as api or worker, ready for Renovate to propose in home-ops. Spec Part B: Deployment (releases).

**Blocked by:** 01 (Walking skeleton)

**Status:** done

- [ ] A release tag triggers build and push of the multi-stage image (frontend export + Python) to GHCR with the version tag
- [x] The image runs non-root with a read-only root filesystem and a writable /tmp
- [x] The workflow runs the CI entrypoint before publishing
