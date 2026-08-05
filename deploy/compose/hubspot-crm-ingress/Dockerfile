FROM nginx:1.27-alpine

# TLS material is gitignored and excluded from the image build context by
# .dockerignore. Mount host certs at runtime via Compose:
#   ./hubspot-crm-ingress/certs:/etc/nginx/certs:ro
# Generate first: bash deploy/compose/hubspot-crm-ingress/generate-certs.sh
COPY deploy/compose/hubspot-crm-ingress/nginx.conf /etc/nginx/conf.d/default.conf
