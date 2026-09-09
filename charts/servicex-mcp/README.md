# servicex-mcp Helm chart

Deploys [servicex-mcp](https://github.com/kratsg/servicex-mcp) over **HTTP
transport** on Kubernetes, in one of two modes selected by `auth.brokerUrl`:

- **Standalone/bridge mode** (default, `auth.brokerUrl` empty): each MCP client
  authenticates by pasting their own ServiceX personal refresh token through the
  server's `/bridge` interstitial (the CIMD OAuth bridge) the first time they
  connect -- no ServiceX credential lives in the pod. Needs a public Ingress.
- **Broker mode** (`auth.brokerUrl` set): the server redeems ServiceX access
  tokens from an [AF MCP broker](https://github.com/maniaclab/af-mcp-platform)
  per call instead of running its own OAuth bridge; clients authenticate with an
  AF Broker Identity Token. No public Ingress needed -- set
  `ingress.enabled: false` and `auth.resourceUrl` explicitly.

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
| `auth.brokerUrl`              | `""`    | AF MCP broker base URL; set to enable broker mode                   |
| `servicexMcp.version`         | `0.1.3` | servicex-mcp release pinned into `pixi.toml`                        |
| `servicexMcp.pixiLockContent` | `""`    | Frozen `pixi.lock` for reproducible installs (`--set-file`)         |
| `readOnly`                    | `true`  | Disable write tools                                                 |
| `ingress.host`                | `""`    | External hostname (required when `ingress.enabled`)                 |

See [`values.yaml`](values.yaml) for the full, documented set.

## Broker mode

```bash
helm install servicex-mcp ./charts/servicex-mcp \
  --namespace mcp --create-namespace \
  --set ingress.enabled=false \
  --set auth.backendUrl=https://servicex.af.uchicago.edu \
  --set auth.resourceUrl=http://servicex-mcp.mcp.svc.cluster.local \
  --set auth.brokerUrl=http://af-mcp-platform-broker.mcp.svc.cluster.local:8080
```

Requires `maniaclab/af-mcp-platform`'s `ServiceXTokenProvider` (redeeming
against a deployed `servicex-token-service`) and an `aggregator.services` entry
pointing at this deployment's in-cluster Service.

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
