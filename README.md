# bind9-ctl

Declarative tooling to plan and apply changes to BIND9 zones by comparing YAML-defined desired state with AXFR snapshots of the live zone.

## Features

- Loads desired state from YAML (optionally Jinja2-templated) files.
- Fetches the authoritative zone via AXFR using TSIG authentication.
- Normalises records into a typed `Record` model and produces diffs.
- Renders new zone files with Jinja2, validates them via `named-checkzone`, and reloads BIND with `rndc`.
- Integrates with git for auditable change management.
- Pulls the live zone state to YAML or JSON snapshots for auditing.
- Applies diffs via TSIG-authenticated dynamic updates (`APPLY_STRATEGY=dynamic`) or traditional zone reloads.

## Installation (Linux)

1. Clone this repository onto the target host.
2. Run the installer (requires root to install packages and create `/usr/local/bin/bind9-ctl`):

   ```bash
   sudo scripts/install-linux.sh
   ```

   Environment variables:

   - `INSTALL_PREFIX` (default `/opt/bind9-ctl`) – installation directory.
   - `CLI_LINK` (default `/usr/local/bin/bind9-ctl`) – wrapper script path.
   - `SKIP_SYSTEM_PACKAGES=1` – skip package installation if dependencies are preinstalled.
   - `PYTHON_BIN` – override Python interpreter (default `python3`).

3. Edit `/opt/bind9-ctl/.env` to point at your BIND server and credentials, then continue with the quick-start flow below.

## Quick start

1. Copy `env.example` to `.env` and adjust values.\
   **Note**: If you keep your TSIG key in the traditional BIND key format, base64‑encode the whole file and place it in `BIND_TSIG_KEYFILE_B64`.

2. Install dependencies (Python ≥ 3.11):

   ```bash
   pip install -e .[dev]
   ```

3. Pull the current zone to inspect or seed YAML:

   ```bash
   bind9-ctl pull --zone local.example.ru. --output zones/local-live.yaml
   ```

4. Choose an apply strategy (default `dynamic`). Set in `.env`:

   ```
   APPLY_STRATEGY=dynamic  # or zone
   ```

5. Edit a YAML declaration such as:

    ```yaml
   zone: local.example.ru.
   default_ttl: 600
   soa:
     primary_ns: ns1.local.example.ru.
     admin_email: hostmaster.local.example.ru.
   records:
     - name: ingress
       type: A
       ttl: 300
       value: 10.10.90.22
     - name: harbor
       type: A
       ttl: 300
       value: 10.10.90.13
     - name: grafana
       type: CNAME
       ttl: 300
       value: ingress.local.example.ru.
   ```

6. Run a plan to see diffs without modifying anything:

   ```bash
   bind9-ctl plan --zone local.example.ru. --desired zones/local.yaml
   ```

7. Apply changes. In `dynamic` mode the tool issues TSIG dynamic updates; in `zone` mode it runs `named-checkzone` + `rndc reload`:

   ```bash
   bind9-ctl apply --zone local.example.ru. --desired zones/local.yaml --yes
   ```
