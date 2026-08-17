FROM nginx:1.27-alpine

# Host *.crt/*.key are dockerignored so they never land in the build context.
# Generate a local self-signed pair in the image or nginx dies on startup.
RUN apk add --no-cache openssl \
    && mkdir -p /etc/nginx/certs \
    && openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
        -keyout /etc/nginx/certs/server.key \
        -out /etc/nginx/certs/server.crt \
        -subj "/CN=hubspot-crm-ingress" \
        -addext "subjectAltName=DNS:hubspot-crm-ingress,DNS:hubspot-crm.local" \
    && chmod 600 /etc/nginx/certs/server.key \
    && apk del openssl

COPY deploy/compose/hubspot-crm-ingress/nginx.conf /etc/nginx/conf.d/default.conf