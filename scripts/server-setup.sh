#!/usr/bin/env bash
# Run once as root on the server. Creates a separate deploy user and folders for Checklists.
set -euo pipefail
U=fhdeploy
id "$U" &>/dev/null || adduser --disabled-password --gecos "" "$U"
usermod -aG docker "$U"          # needs Docker installed; NOTE: docker group ~ root-equivalent
mkdir -p /var/www/checklists/releases /opt/checklists/backend /srv/checklists/uploads /srv/checklists/backups /var/www/letsencrypt
chown -R "$U":"$U" /var/www/checklists /opt/checklists
chown 1001:1001 /srv/checklists/uploads      # API container runs as uid 1001
chmod 755 /srv/checklists /srv/checklists/uploads
install -d -m 700 -o "$U" -g "$U" /home/$U/.ssh
echo "1) Append the deploy PUBLIC key to /home/$U/.ssh/authorized_keys"
echo "2) Create /opt/checklists/backend/.env from backend/.env.production.example (strong passwords!)"
echo "3) Copy nginx/checklists.conf to /etc/nginx/conf.d/, edit host name, nginx -t && systemctl reload nginx"
