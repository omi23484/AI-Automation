# NetEng Toolkit

NetEng Toolkit is a self-installing, offline-first Linux web application for network engineering workflows. The repository ships a single installer script, [`neteng-toolkit.sh`](./neteng-toolkit.sh), which generates a standalone HTML/CSS/JavaScript application and runs it as a `systemd` service on port `8443`.

The browser app has no CDN dependencies and stores data locally unless you explicitly import, export, or sync a JSON file.

## Quick start

From this repository folder:

```bash
sudo bash neteng-toolkit.sh install
```

Then open the app in a browser:

```text
http://localhost:8443/
```

Default credentials:

```text
Username: admin
Password: admin123
```

> Change the default password after first login from **Settings**.

## Requirements

- Linux host with `systemd`
- `bash`
- `python3`
- A modern browser with Web Crypto API support
- Root privileges for install/uninstall operations

## Install

Run:

```bash
sudo bash neteng-toolkit.sh install
```

The installer will:

1. Create `/opt/neteng-toolkit`.
2. Write the embedded browser app to `/opt/neteng-toolkit/index.html`.
3. Create `/etc/systemd/system/neteng-toolkit.service`.
4. Enable and start the service.
5. Serve the app on HTTP port `8443`.

## Operate the service

Check service status:

```bash
sudo systemctl status neteng-toolkit
```

Start the service:

```bash
sudo systemctl start neteng-toolkit
```

Stop the service:

```bash
sudo systemctl stop neteng-toolkit
```

Restart the service:

```bash
sudo systemctl restart neteng-toolkit
```

View service logs:

```bash
sudo journalctl -u neteng-toolkit -f
```

Open the app:

```text
http://localhost:8443/
```

If you are connecting from another machine, replace `localhost` with the server IP or DNS name:

```text
http://SERVER_IP_OR_NAME:8443/
```

Make sure host firewall rules allow inbound TCP `8443` if remote access is required.

## Uninstall

Run:

```bash
sudo bash neteng-toolkit.sh uninstall
```

The uninstall routine stops/disables the service, removes the systemd unit, reloads systemd, and deletes `/opt/neteng-toolkit`.

## Browser app operation

### Login and password management

1. Open `http://localhost:8443/`.
2. Log in with `admin / admin123`.
3. Select **Settings**.
4. Enter the current password and a new password.
5. Click **Change password**.

Passwords are hashed in the browser with PBKDF2 + SHA-256 using the Web Crypto API. Authentication data is stored locally in browser storage.

### Data storage

The app is offline-first:

- `localStorage` stores session/theme/auth metadata.
- IndexedDB stores workspace data such as notes, templates, tasks, inventory, knowledge base entries, OUI mappings, and diagrams.
- No application state is sent to any remote service by the toolkit.

Browser storage is per browser profile and per origin. If you open the app from a different hostname, IP, browser, or profile, it may have separate local data.

### Backup and restore

Use **Settings** or the dashboard backup controls to:

- **Export JSON**: download a full local backup.
- **Import backup JSON**: restore workspace/auth/theme data from a backup file.
- **Optional JSON Sync**: use the File System Access API when supported by the browser to save a JSON sync file.

## Included modules

### Addressing

- IPv4 subnet calculator
- Wildcard/mask converter
- VLSM planner
- IPv6 calculator
- MAC/OUI lookup and format converter with custom OUI import/export

### Crypto and conversion

- Base64, hex, binary, and URL conversion
- Hash generator
- Password generator

### Configuration engineering

- Config templates
- CSV-to-config generator
- Jinja-like playground
- Config diff
- ACL builder
- CDP/LLDP topology parser
- Route-map/prefix-list tester
- Cisco cheatsheet
- Local knowledge base

### Operations

- Port reference
- Bandwidth calculator
- MTU/MSS calculator
- PoE budget calculator
- Timezone/change-window planner
- Diagram tool
- Scratchpad
- Task tracker
- Inventory
- Regex tester
- JSON/YAML/XML viewer

## Security notes

- The service is served over plain HTTP by default on port `8443` using Python's built-in HTTP server.
- The browser app uses Web Crypto for password hashing, but this is still a local administrative gate for an offline toolkit, not a replacement for network-layer access control.
- Restrict access with host firewall rules, VPN, reverse proxy authentication, or SSH tunneling if exposing the service beyond localhost or a trusted management network.
- Change the default `admin123` password immediately after installation.

## Troubleshooting

### Port already in use

Check what is using port `8443`:

```bash
sudo ss -ltnp 'sport = :8443'
```

Stop the conflicting service or edit `PORT="8443"` in `neteng-toolkit.sh` before reinstalling.

### Service failed to start

Check status and logs:

```bash
sudo systemctl status neteng-toolkit
sudo journalctl -u neteng-toolkit --no-pager -n 100
```

Confirm `python3` is installed:

```bash
python3 --version
```

### Browser data appears missing

Confirm you are using the same browser profile and the same origin, for example `http://localhost:8443` versus `http://SERVER_IP:8443`. Browser storage is scoped by origin.

## Development checks

Basic checks used for this repository:

```bash
bash -n neteng-toolkit.sh
```

```bash
awk '/<script>/{flag=1;next}/<\/script>/{flag=0}flag' neteng-toolkit.sh > /tmp/neteng-toolkit.js
node --check /tmp/neteng-toolkit.js
```
