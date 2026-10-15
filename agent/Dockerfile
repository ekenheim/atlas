# syntax=docker/dockerfile:1
# The scheduled agents (atlas-beliefs ticket 17): headless Claude Code (`claude -p`) running the
# Scout, Researcher and Skeptic routines against Atlas's MCP server. Built from the repo root:
#   docker build -f agent/Dockerfile -t atlas-agent:dev .
# No secrets in the image: the owner's `claude setup-token` token arrives as
# CLAUDE_CODE_OAUTH_TOKEN from a Kubernetes Secret at run time.

# Node LTS (24), exact version and the tag's index digest. Bump both together.
FROM node:24.21.0-bookworm-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20

# An exact published version, at least two weeks old when pinned (2.1.286: 2026-09-30).
# npm must install the platform's optional dependency (the native binary): no --omit=optional.
ARG CLAUDE_CODE_VERSION=2.1.286
RUN npm install --global --no-audit --no-fund "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
    && npm cache clean --force \
    && claude --version

# The repo's layout under /opt/atlas-agent: the routine runs with this as its working directory,
# so `.claude/skills/atlas-research/` is the project's skill and the prompts name it by that path.
COPY --chmod=0755 agent/ /opt/atlas-agent/agent/
COPY .claude/skills/atlas-research/ /opt/atlas-agent/.claude/skills/atlas-research/

# Non-root; the root filesystem is read-only in the cluster, /tmp (an emptyDir) is the only
# writable place: Claude Code's state (HOME) and the run's output folder (/tmp/out).
USER 10001
ENV HOME=/tmp \
    DISABLE_AUTOUPDATER=1 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
WORKDIR /opt/atlas-agent
ENTRYPOINT ["/opt/atlas-agent/agent/run.sh"]
CMD ["--help"]
