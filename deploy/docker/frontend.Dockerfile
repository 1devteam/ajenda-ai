FROM node:22-alpine AS build

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ .

# Same-origin API calls when ingress or compose nginx proxies /v1 to the API.
# Never bake local frontend/.env dev credentials into production images.
# Do not declare credential-shaped ENV keys (even empty) — they surface in image
# config metadata and scanners treat them as secret-bearing surfaces.
RUN rm -f .env .env.local .env.development .env.development.local
ENV VITE_API_BASE_URL=
RUN npm run build

FROM nginx:1.27-alpine

ARG NGINX_CONF=deploy/nginx/frontend.compose.conf
COPY ${NGINX_CONF} /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
