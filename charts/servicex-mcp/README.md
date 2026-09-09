# servicex-mcp Helm chart

Deploys [servicex-mcp](https://github.com/kratsg/servicex-mcp) over **HTTP
transport** on Kubernetes. Each MCP client authenticates by pasting their own
ServiceX personal refresh token through the server's `/bridge` interstitial (the
CIMD OAuth bridge) the first time they connect -- no ServiceX credential lives
in the pod, and there is exactly one auth model, unlike rucio-mcp's `auth.mode`
(oidc / sharedSecret / broker).

There is no published servicex-mcp container image: an init container runs the
`ghcr.io/prefix-dev/pixi` image and installs the pinned `servicexMcp.version`
from conda-forge into a shared volume at pod startup.

## Quick start

```bash
helm install servicex-mcp ./charts/servicex-mcp \
  --namespace mcp --create-namespace \
  --set ingress.host=servicex-mcp.example.com \
  --set auth.backendUrl=https://servicex.af.uchicago.edu
```

## Key values

| Key                           | Default | Description                                                         |
| ----------------------------- | ------- | ------------------------------------------------------------------- |
| `auth.backendUrl`             | `""`    | Base URL of the ServiceX deployment this server talks to (required) |
| `auth.resourceUrl`            | `""`    | Public URL of this server; derived from `ingress.host` if empty     |
| `servicexMcp.version`         | `0.1.1` | servicex-mcp release pinned into `pixi.toml`                        |
| `servicexMcp.pixiLockContent` | `""`    | Frozen `pixi.lock` for reproducible installs (`--set-file`)         |
| `readOnly`                    | `true`  | Disable write tools                                                 |
| `ingress.host`                | `""`    | External hostname (required when `ingress.enabled`)                 |

See [`values.yaml`](values.yaml) for the full, documented set.

## Freezing the deployed version

By default `pixi install` resolves dependencies fresh at each pod start. For
reproducible rollouts, generate a lock against the rendered `pixi.toml` after a
release and feed it back in:

```bash
helm template s ./charts/servicex-mcp --show-only templates/configmap.yaml \
  --set ingress.host=servicex-mcp.example.com \
  --set auth.backendUrl=https://servicex.af.uchicago.edu \
  | yq '.data["pixi.toml"]' > /tmp/pixi.toml
pixi lock --manifest-path /tmp/pixi.toml          # writes /tmp/pixi.lock
helm upgrade servicex-mcp ./charts/servicex-mcp \
  --reuse-values --set-file servicexMcp.pixiLockContent=/tmp/pixi.lock
```

Full documentation: see the project docs (TODO: not yet written -- see
`docs/plans/` in the meantime).
