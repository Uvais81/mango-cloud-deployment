# MangoCloud SDK Docker Compose

## Overview
This repository lets you run the Mango Cloud / OpenWifi stack with Docker Compose. In addition to the core controller services, the current setup also supports:

- Grafana-based monitoring through the `monitoring` Compose profile
- AI agent services through the `ai-agent` Compose profile
- Same-origin proxy access from `owgw-ui` for both Grafana and the AI chat endpoint

The repository contains self-signed certificates and TIP-signed gateway certificates for the `*.wlan.local` domain. You can also replace them with your own certificates or use Let's Encrypt for remote deployments.

## Mango Cloud Components
![Mango Cloud component architecture](./mango-cloud-components.drawio.png)

This deployment includes:

- `owgw-ui` and `owprov-ui` as the main user-facing web interfaces
- Core backend services: `owgw`, `owsec`, `owfms`, `owprov`, `owanalytics`, `owsub`, and `network-topology`
- `kafka` for inter-service messaging and `postgresql` for persistent storage
- Optional monitoring services: `prometheus`, `grafana`, `cadvisor`, `node-exporter`, `postgres-exporter`, `kafka-exporter`, and `otel-collector`
- Optional AI agent services: `mcp-server` and `mcp-client`

## Build Your Own Images
All Mango Cloud component repositories are public. You can clone these repos, build your own Docker images, and update image references or tags in the Compose files.

- `owgw`: https://github.com/routerarchitects/ra-wlan-cloud-ucentralgw/tree/release/v1.0.0
- `owgw-ui`: https://github.com/routerarchitects/ra-wlan-cloud-ucentralgw-ui/tree/release/v1.0.0
- `owprov`: https://github.com/routerarchitects/ra-wlan-cloud-owprov/tree/release/v1.0.0
- `owprov-ui`: https://github.com/routerarchitects/ra-wlan-cloud-owprov-ui/tree/release/v1.0.0
- `owanalytics`: https://github.com/routerarchitects/ra-wlan-cloud-analytics/tree/release/v1.0.0
- `owsec`: https://github.com/routerarchitects/ra-wlan-cloud-ucentralsec/tree/release/v1.0.0
- `owfms`: https://github.com/routerarchitects/ra-wlan-cloud-ucentralfms/tree/release/v1.0.0
- `owsub` (user portal): https://github.com/routerarchitects/ra-wlan-cloud-userportal/tree/release/v1.0.0
- `network-topology`: https://github.com/routerarchitects/ra-openlan-nw-topology/tree/release/v1.0.0

---
## Local Setup

Commands below use `docker-compose`. If your system uses Docker Compose v2, `docker compose` is equivalent.

### 1. Clone the repository
```bash
mkdir openwifi-sdk
cd openwifi-sdk
git clone https://github.com/routerarchitects/mango-cloud-deployment.git
cd mango-cloud-deployment/docker-compose/
```

Do not switch to `release/v1.0.0` if you want the AI agent and Grafana monitoring setup described in this README. These instructions assume the current repository state.

### 2. Install Docker and Docker Compose
```bash
sudo apt install docker.io docker-compose -y
sudo usermod -aG docker $USER
newgrp docker
sudo chown -R $USER:$USER .
```

### 3. Configure firmware image settings in `owfms.env`
These settings are used by `owgw-ui` and `owprov-ui` to show the correct device group and device type. They are also required for firmware upgrades.

Update the firmware bucket values in `owfms.env`:
```env
S3_BUCKETNAME=<firmware-bucket-name>
S3_REGION=<aws-region>
S3_SECRET=<s3-secret-key>
S3_KEY=<s3-access-key>
S3_BUCKET_URI=s3.<aws-region>.amazonaws.com/<firmware-bucket-name>
FIRMWAREDB_MAXAGE=365  # Firmware image expiry time in days. Default value is 90.
```

### 4. Configure subscriber email verification in `owsec.env`
The Security service (`owsec`) sends subscriber verification emails. If you use Gmail, first create an app password here:

[Google App Passwords](https://myaccount.google.com/apppasswords)

Then update `owsec.env`:
```env
MAILER_ENABLED=true
MAILER_HOSTNAME=smtp.gmail.com
MAILER_USERNAME=<Email used to create the app-password>
MAILER_PASSWORD=<app-password>
MAILER_SENDER=Sender Name <sender email>
MAILER_PORT=587
MAILER_TEMPLATES=$OWSEC_ROOT/templates
```

### 5. Update certificates
Certificates are required for secure communication between devices and the controller (`owgw`). Use a common CA or issuer for both controller certificates and device certificates.

Use this guide to generate the required certificates:

[mango_cloud_cert_generation](https://github.com/routerarchitects/mango_cloud_cert_generation)

After generating them, replace these files in `certs/`:
```text
clientcas.pem
issuer.pem
root.pem
websocket-cert.pem
websocket-key.pem
```

### 6. Configure Grafana monitoring
The monitoring stack is optional and runs through the `monitoring` Compose profile.

Important local defaults:

- `grafana.env` already points Grafana to `https://openwifi.wlan.local/grafana/`
- `owgw-ui.env` already points the UI to the bundled Grafana dashboards
- Grafana is exposed through `owgw-ui` at `/grafana/`, not directly on port `3000`

The monitoring profile includes:

- `prometheus`
- `grafana`
- `cadvisor`
- `node-exporter`
- `postgres-exporter`
- `kafka-exporter`
- `otel-collector`

### 7. Configure the AI agent
The AI agent is optional and runs through the `ai-agent` Compose profile.

Before starting it:

1. Update `ai-agent.env` with your own API keys and origin.
2. Make sure the monitoring stack is enabled first, because the AI agent reads metrics from `PROMETHEUS_URL=http://prometheus:9090`.
3. If you change `AGENT_API_KEY`, update the same value in `owgw-ui/default.conf` for the `X-API-Key` header used by the `/ai/chat` proxy.

Recommended `ai-agent.env` values:
```env
# Use the provider you need
OPENAI_API_KEY=<your-openai-api-key>
OPENAI_MODEL=gpt-4o-mini

# Or configure Gemini instead
GEMINI_API_KEY=<your-gemini-api-key>
GEMINI_MODEL=gemini-2.5-flash

NODE_DEVICE_HOSTNAME=<Enter-Your-Machine-Hostname>
PROMETHEUS_URL=http://prometheus:9090
ALLOWED_ORIGIN=https://openwifi.wlan.local
AGENT_API_KEY=<set-a-strong-shared-key>
PRODUCTION_MODE=true
REQUIRE_API_KEY=true
VERIFY_TLS=false
```

Notes:

- Keep `VERIFY_TLS=false` unless you provide internal certificates that match the Docker DNS name `mcp-server`
- Keep `RAG_ENABLED=false` unless you also configure the `QDRANT_*` settings
- Configure `SMTP_*` and `ALERT_*` values only if you want the AI agent to send alert emails
- The current Compose file builds `mcp-server` and `mcp-client` from local source paths; if those paths do not exist in your environment, update the `build:` paths or use your own image references before starting the AI profile

### 8. Start the core OpenWiFi stack
```bash
docker-compose down --remove-orphans
docker-compose up -d
```

### 9. Add the local hostname mapping
The local UI URLs use `openwifi.wlan.local`, so add it to `/etc/hosts`:
```bash
echo "127.0.0.1 openwifi.wlan.local" | sudo tee -a /etc/hosts
```

### 10. Enable Grafana monitoring from the `owgw-ui` dashboard

1. Log in to `https://openwifi.wlan.local`
2. Open `System > Advanced`
3. Turn on `Enable Monitoring (Grafana) Tab`

This dashboard toggle shows the Grafana tab and uses the backend monitoring control endpoint to start or stop the monitoring containers.

If you prefer CLI or the toggle does not work yet, use:
```bash
docker-compose --profile monitoring up -d
```

### 11. Enable the AI assistant from the `owgw-ui` dashboard
Enable the AI assistant only after monitoring is already enabled and healthy.

1. Stay on `System > Advanced`
2. Turn on `Enable AI Assistant`
3. Confirm that the AI assistant button appears in the navbar

If the toggle shows `Unavailable`, check the monitoring stack first and then start the AI agent with:
```bash
docker-compose --profile ai-agent up -d
```

### 12. Verify access
```text
Controller UI:
https://openwifi.wlan.local

Provisioning UI:
https://openwifi.wlan.local:8443

Service control health:
https://openwifi.wlan.local/api/v1/service-control/healthz

Default UI credentials:
Username: tip@ucentral.com
Password: openwifi
```

### 13. Quick health checks
```bash
docker-compose ps
curl -k https://openwifi.wlan.local/api/v1/service-control/healthz
```

### 14. Required password change after first startup
Before using the deployment in practice, change the default password for the default `owsec` user as described in the official docs:

https://github.com/Telecominfraproject/wlan-cloud-ucentralsec/tree/main#changing-default-password

---
## Remote Setup

- Create an EC2 instance
- Use an instance with at least 8 GB RAM
- Use Ubuntu 22.04.3 LTS or later
- Complete the local setup first for `owfms.env`, `owsec.env`, certificates, Grafana settings, and AI agent settings

### 1. Update the security group
Allow these inbound ports:

```text
TCP: 22, 80, 443, 5000, 5912, 5913, 8443, 15002, 16001, 16002, 16003, 16004, 16005, 16006, 16007, 16009
```

Optional direct-access ports:

- `8787` if you want to reach the AI agent directly instead of using `/ai/chat`
- `9090` if you want direct Prometheus access

### 2. SSH into the server
```bash
ssh -i <your-key.pem> ubuntu@<EC2-PUBLIC-IP>
```

If the repository is not already on the server, clone it and move into the deployment directory:
```bash
mkdir -p ~/openwifi-sdk
cd ~/openwifi-sdk
git clone https://github.com/routerarchitects/mango-cloud-deployment.git
cd mango-cloud-deployment/docker-compose/
```

### 3. Install required tools
```bash
sudo apt update
sudo apt install net-tools certbot -y
```

### 4. Choose the public hostname
Use only the hostname, without `https://`.

```bash
PUBLIC_HOSTNAME=<your-public-domain>
echo "$PUBLIC_HOSTNAME"
```

### 5. Prepare public certificate placeholders
```bash
bash ./update_openwifi_public_certs.sh
```

### 6. Update hostname references
Replace `openwifi.wlan.local` in all env files:
```bash
sudo find . -type f -name "*.env" -exec sed -i.bak "s|openwifi\.wlan\.local|$PUBLIC_HOSTNAME|g" {} +
```

This also updates the hostname values used by:

- `grafana.env`
- `owgw-ui.env`
- `ai-agent.env`

If you also change `AGENT_API_KEY`, update the matching `X-API-Key` value in `owgw-ui/default.conf`.

### 7. Generate Let's Encrypt certificates
```bash
sudo certbot certonly --standalone \
  --key-type rsa \
  --cert-name $PUBLIC_HOSTNAME \
  -d $PUBLIC_HOSTNAME \
  -m your-email@example.com \
  --agree-tos --non-interactive --force-renewal
```

Certificates will be created in:
```text
/etc/letsencrypt/live/<PUBLIC_HOSTNAME>/
```

Copy them into the deployment directory:
```bash
cd /home/ubuntu/openwifi-sdk/mango-cloud-deployment/docker-compose

sudo cp /etc/letsencrypt/live/$PUBLIC_HOSTNAME/privkey.pem certs/restapi-public-key.pem
sudo cp /etc/letsencrypt/live/$PUBLIC_HOSTNAME/fullchain.pem certs/restapi-public-cert.pem
sudo cp /etc/letsencrypt/live/$PUBLIC_HOSTNAME/chain.pem certs/restapi-public-ca.pem

sudo chown ubuntu:ubuntu certs/restapi-public-*.pem
sudo chmod 664 certs/restapi-public-*.pem
ls -l certs/
```

### 8. Update `docker-compose.yml` for remote UI certificates
After generating the public certificates, update the certificate mount paths in `docker-compose.yml` for both `owgw-ui` and `owprov-ui`.

Replace:
```yaml
- "./certs/restapi-cert.pem:/etc/nginx/restapi-cert.pem"
- "./certs/restapi-key.pem:/etc/nginx/restapi-key.pem"
```

With:
```yaml
- "./certs/restapi-public-cert.pem:/etc/nginx/restapi-cert.pem"
- "./certs/restapi-public-key.pem:/etc/nginx/restapi-key.pem"
```

### 9. Start the core OpenWiFi stack
```bash
docker-compose down --remove-orphans
docker-compose up -d
```

### 10. Enable Grafana monitoring from the `owgw-ui` dashboard

1. Log in to `https://<PUBLIC_HOSTNAME>`
2. Open `System > Advanced`
3. Turn on `Enable Monitoring (Grafana) Tab`

This dashboard toggle shows the Grafana tab and uses the backend monitoring control endpoint to start or stop the monitoring containers.

If you prefer CLI or the toggle does not work yet, use:
```bash
docker-compose --profile monitoring up -d
```

### 11. Enable the AI assistant from the `owgw-ui` dashboard
Enable the AI assistant only after monitoring is already enabled and healthy.

1. Stay on `System > Advanced`
2. Turn on `Enable AI Assistant`
3. Confirm that the AI assistant button appears in the navbar

If the toggle shows `Unavailable`, check the monitoring stack first and then start the AI agent with:
```bash
docker-compose --profile ai-agent up -d
```

### 12. Verify access
```text
Controller UI:
https://<PUBLIC_HOSTNAME>

Provisioning UI:
https://<PUBLIC_HOSTNAME>:8443

Service control health:
https://<PUBLIC_HOSTNAME>/api/v1/service-control/healthz

Default UI credentials:
Username: tip@ucentral.com
Password: openwifi
```

### 13. Quick health checks
```bash
docker-compose ps
curl -k https://<PUBLIC_HOSTNAME>/api/v1/service-control/healthz
```

### Automated Let's Encrypt Certificate Renewal
#### Create the deploy hook script

Note: replace `<PUBLIC_HOSTNAME>` in the script below with your actual hostname.

Create the file:
```bash
sudo tee /usr/local/bin/openwifi-sdk-renew-certs-hook.sh > /dev/null << 'EOF'
#!/bin/bash

LOG_FILE="/var/log/letsencrypt-renewal.log"
CERT_DIR="/home/ubuntu/openwifi-sdk/mango-cloud-deployment/docker-compose/certs"
LE_DIR="/etc/letsencrypt/live/<PUBLIC_HOSTNAME>"
START_MONITORING_AFTER_RENEWAL=true
START_AI_AGENT_AFTER_RENEWAL=true

echo "[openwifi-cert-renewal] Certificate renewed at $(date)" > "$LOG_FILE"

cp "$LE_DIR/fullchain.pem" "$CERT_DIR/restapi-public-cert.pem"
cp "$LE_DIR/privkey.pem"   "$CERT_DIR/restapi-public-key.pem"
cp "$LE_DIR/chain.pem"     "$CERT_DIR/restapi-public-ca.pem"

chown ubuntu:ubuntu -R "$CERT_DIR"/restapi-public*.pem
chmod 664 "$CERT_DIR"/restapi-public*.pem

cd /home/ubuntu/openwifi-sdk/mango-cloud-deployment/docker-compose || exit

/usr/bin/docker-compose down
/usr/bin/docker-compose up -d

if [ "$START_MONITORING_AFTER_RENEWAL" = "true" ]; then
  /usr/bin/docker-compose --profile monitoring up -d
fi

if [ "$START_AI_AGENT_AFTER_RENEWAL" = "true" ]; then
  /usr/bin/docker-compose --profile ai-agent up -d
fi

echo "[openwifi-cert-renewal] Docker Compose restarted at $(date)" >> "$LOG_FILE"
EOF
```

Set `START_MONITORING_AFTER_RENEWAL=false` or `START_AI_AGENT_AFTER_RENEWAL=false` if you are not using those optional profiles.

Make it executable:
```bash
sudo chmod +x /usr/local/bin/openwifi-sdk-renew-certs-hook.sh
```

#### Create the renewal wrapper script
This script checks whether the current certificate will expire within the next 48 hours. If yes, it forces renewal and then runs the deploy hook.

```bash
sudo tee /usr/local/bin/openwifi-sdk-renew-certs.sh > /dev/null << 'EOF'
#!/bin/bash
set -euo pipefail

CERT_FILE="/etc/letsencrypt/live/<PUBLIC_HOSTNAME>/cert.pem"
HOOK_SCRIPT="/usr/local/bin/openwifi-sdk-renew-certs-hook.sh"
LOG_FILE="/var/log/letsencrypt-renewal.log"

if ! openssl x509 -checkend 172800 -noout -in "$CERT_FILE"; then
  echo "[openwifi-cert-renewal] Certificate expires in less than 48 hours. Renewing at $(date)" >> "$LOG_FILE"
  certbot renew --cert-name <PUBLIC_HOSTNAME> --force-renewal --quiet
  "$HOOK_SCRIPT"
else
  echo "[openwifi-cert-renewal] Certificate is still valid for more than 48 hours. No renewal needed at $(date)" >> "$LOG_FILE"
fi
EOF
```

Make it executable:
```bash
sudo chmod +x /usr/local/bin/openwifi-sdk-renew-certs.sh
```

#### Set up the cron job
Edit the root crontab:
```bash
sudo crontab -e
```

Add this entry:
```text
17 */12 * * * /usr/local/bin/openwifi-sdk-renew-certs.sh
```

This checks the certificate every 12 hours and renews it only when less than 48 hours remain before expiry.

Check the crontab:
```bash
sudo crontab -l
```

#### Test the renewal logic

```bash
sudo bash /usr/local/bin/openwifi-sdk-renew-certs.sh
```
To verify the current certificate expiry date:
```bash
sudo openssl x509 -enddate -noout -in /etc/letsencrypt/live/<PUBLIC_HOSTNAME>/cert.pem
```
