#!/bin/bash
# Run this once after first deployment to generate SSL certs
# Usage: sudo ./docker/init-ssl.sh api.manakrishi.in your@email.com

DOMAIN=${1:-api.manakrishi.in}
EMAIL=${2:-admin@manakrishi.in}

if [ -z "$DOMAIN" ]; then
  echo "Usage: ./init-ssl.sh <domain> <email>"
  exit 1
fi

echo "=== Generating SSL certificate for $DOMAIN ==="

# Make sure nginx is running (HTTP only) for ACME challenge
sudo docker compose -f docker-compose.prod.yml up -d nginx

# Request certificate
sudo docker compose -f docker-compose.prod.yml run --rm certbot \
  certonly --webroot --webroot-path=/var/www/certbot \
  --email $EMAIL --agree-tos --no-eff-email \
  -d $DOMAIN

if [ $? -eq 0 ]; then
  echo ""
  echo "✅ SSL certificate generated successfully!"
  echo ""
  echo "Now enabling HTTPS in nginx..."
  
  # Replace nginx config with SSL-enabled version
  cat > docker/nginx.conf << NGINXEOF
upstream django {
    server web:8000;
}

server {
    listen 80;
    server_name $DOMAIN;
    client_max_body_size 10M;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://\\\$host\\\$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name $DOMAIN;
    client_max_body_size 10M;

    ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;

    location /static/ {
        alias /app/staticfiles/;
        expires 30d;
    }

    location /health/ {
        proxy_pass http://django;
        access_log off;
    }

    location / {
        proxy_pass http://django;
        proxy_set_header Host \\\$host;
        proxy_set_header X-Real-IP \\\$remote_addr;
        proxy_set_header X-Forwarded-For \\\$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_connect_timeout 30s;
        proxy_read_timeout 120s;
    }
}
NGINXEOF

  # Restart nginx with new config
  sudo docker compose -f docker-compose.prod.yml restart nginx
  echo "✅ HTTPS enabled! Site live at https://$DOMAIN"
else
  echo "❌ Certificate generation failed. Make sure:"
  echo "   1. Domain $DOMAIN points to this server's IP"
  echo "   2. Port 80 is open"
  echo "   3. Try again after DNS propagation"
fi
