# sidecar-probe-e2e

External probe-contract tests for flags-2-env-sidecar.

External / end-user tests. They do not import product crates.

```sh
python -m unittest discover -s tests -v
SIDECAR_URL=http://127.0.0.1:9090 python -m unittest discover -s tests -v
```
