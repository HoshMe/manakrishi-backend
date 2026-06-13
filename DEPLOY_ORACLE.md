# Oracle Cloud Free Tier Deployment Guide

## What you get (Always Free):
- **VM.Standard.A1.Flex** — Up to 4 ARM CPUs, 24GB RAM (Ampere A1)
- **Boot volume** — 200GB total
- **Outbound data** — 10TB/month
- **Load Balancer** — 1 flexible LB (10Mbps)

## Recommended split for ManaKrishi:
- 1 VM: 2 OCPUs, 12GB RAM (Django + Celery + Redis + Nginx)
- Or 2 VMs: 2 OCPUs + 12GB each (separate web & worker)

---

## Step 1: Create Oracle Cloud VM

1. Sign up at https://cloud.oracle.com (free tier)
2. Compute → Create Instance:
   - Shape: `VM.Standard.A1.Flex` (ARM)
   - OCPUs: 2, RAM: 12GB
   - Image: **Ubuntu 22.04 (aarch64)**
   - Add SSH key
   - Open ports: 80, 443, 22 in Security List

3. Note the public IP

---

## Step 2: Server Setup (SSH into VM)

```bash
ssh ubuntu@<PUBLIC_IP>

# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker ubuntu
newgrp docker

# Install Docker Compose
sudo apt install docker-compose-plugin -y

# Verify
docker --version
docker compose version
```

---

## Step 3: Deploy

```bash
# Clone repo
git clone https://github.com/<your-repo>/manakrishi_backend.git /opt/manakrishi
cd /opt/manakrishi

# Create prod env file
cp .env.example .env.prod
nano .env.prod  # Fill in Neon DB URL, R2 creds, Razorpay, AWS keys

# Build and start (ARM-compatible)
docker compose -f docker-compose.prod.yml up --build -d

# Create superuser
docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser

# Check logs
docker compose -f docker-compose.prod.yml logs -f web
```

---

## Step 4: Domain & SSL (free with Cloudflare)

1. Point domain A record → Oracle VM public IP
2. Cloudflare → SSL → Full (strict)
3. Or use Let's Encrypt with certbot:

```bash
sudo apt install certbot
sudo certbot certonly --standalone -d api.manakrishi.com
```

Update nginx.conf to use SSL certs.

---

## Step 5: Firewall (Oracle Security List)

In Oracle Console → Networking → VCN → Security Lists → Add Ingress Rules:

| Port | Protocol | Source |
|------|----------|--------|
| 22   | TCP      | Your IP |
| 80   | TCP      | 0.0.0.0/0 |
| 443  | TCP      | 0.0.0.0/0 |

Also on the VM:
```bash
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

---

## Step 6: Auto-restart on reboot

```bash
sudo systemctl enable docker
# Docker compose services have restart: always — they auto-start
```

---

## CI/CD: GitHub Actions → Oracle Cloud

Set these GitHub Secrets:
- `PROD_HOST` = Oracle VM public IP
- `PROD_USER` = ubuntu
- `PROD_SSH_KEY` = your private SSH key

The existing `.github/workflows/ci-cd.yml` handles the rest.
