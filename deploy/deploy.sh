#!/usr/bin/env bash
# Publishes the spirograph page on an Ubuntu/Debian server with nginx and a free HTTPS certificate.
# Expects the page at /tmp/spirograph-index.html. Optional: DOMAIN=example.com (its A record must point to this server).
# Without DOMAIN it uses <ip-with-dashes>.sslip.io, a free name that always resolves to this server's IP.
set -euo pipefail

SRC=/tmp/spirograph-index.html
ROOT=/var/www/spirograph
[ -f "$SRC" ] || { echo "Нет файла $SRC"; exit 1; }

IP=$(curl -4 -fsS https://api.ipify.org || hostname -I | awk '{print $1}')
DOMAIN=${DOMAIN:-${IP//./-}.sslip.io}
echo "==> Адрес сайта: $DOMAIN (IP $IP)"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nginx certbot python3-certbot-nginx >/dev/null

mkdir -p "$ROOT"
install -m 644 "$SRC" "$ROOT/index.html"

cat > /etc/nginx/sites-available/spirograph <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;
    root $ROOT;
    index index.html;
    location / { try_files \$uri \$uri/ =404; }
    gzip on;
    gzip_types text/html text/css application/javascript;
}
EOF
ln -sf /etc/nginx/sites-available/spirograph /etc/nginx/sites-enabled/spirograph
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx
systemctl reload nginx

if command -v ufw >/dev/null && ufw status | grep -q active; then
  ufw allow 'Nginx Full' >/dev/null
fi

if certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email --redirect; then
  echo
  echo "Готово: https://$DOMAIN"
else
  echo
  echo "HTTPS получить не удалось, сайт работает по http://$DOMAIN"
  echo "(без HTTPS браузер не даст записывать видео; проверьте, что порт 80 открыт и домен указывает на $IP)"
fi
