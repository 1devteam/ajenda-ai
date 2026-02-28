# SSL/TLS Certificates

Place your SSL certificate files here:

| File | Description |
|------|-------------|
| `fullchain.pem` | Full certificate chain (certificate + intermediates) |
| `privkey.pem` | Private key (keep secret, never commit to git) |

## Obtaining Certificates

### Option A — Let's Encrypt (recommended for production)

```bash
# Install certbot
sudo apt install certbot

# Obtain certificate (standalone mode — stop nginx first)
sudo certbot certonly --standalone -d yourdomain.com -d www.yourdomain.com

# Certificates will be at:
# /etc/letsencrypt/live/yourdomain.com/fullchain.pem
# /etc/letsencrypt/live/yourdomain.com/privkey.pem

# Copy to this directory
sudo cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem ./fullchain.pem
sudo cp /etc/letsencrypt/live/yourdomain.com/privkey.pem ./privkey.pem
sudo chmod 600 ./privkey.pem
```

### Option B — Self-signed (development/staging only)

```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout privkey.pem \
  -out fullchain.pem \
  -subj "/C=US/ST=State/L=City/O=Omnipath/CN=localhost"
```

### Auto-renewal (Let's Encrypt)

Add to crontab (`crontab -e`):

```
0 3 * * * certbot renew --quiet && docker compose -f docker-compose.production.yml exec nginx nginx -s reload
```

## Security Notes

- `privkey.pem` is listed in `.gitignore` — never commit it
- Set file permissions: `chmod 600 privkey.pem`
- Rotate certificates before expiry (Let's Encrypt certificates expire after 90 days)
