# Restore cluster access and confirm dev-machine reachability

Type: task
Status: open
Blocked by: none

## Question

kubectl rejects the `admin@home-kubernetes` credentials. Before the bake-off and the deploy decisions:

1. **(Human)** Refresh the kubeconfig credentials for `admin@home-kubernetes` (e.g. re-export from talos/the cluster bootstrap, or however this cluster issues them).
2. **(Agent, after 1)**
   - Confirm the live Hindsight image tag in `llm`.
   - Confirm that the LiteLLM proxy (`litellm.llm:4000` or its internal route) and SearXNG are reachable **from WSL**, so local Compose can use them.
   - Record the URLs, and whether a LiteLLM dev key is needed for local use.

Resolved when access works; the answer records the reachable URLs and where the dev credentials live.
