FROM node:22-alpine AS build

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ .

# Same-origin API calls when ingress or compose nginx proxies /v1 to the API.
# Never bake local frontend/.env dev credentials into production images.
RUN rm -f .env .env.local .env.development .env.development.local
ENV VITE_API_BASE_URL=
ENV VITE_DEFAULT_TENANT_ID=
ENV VITE_DEFAULT_API_KEY=
RUN npm run build

FROM nginx:1.27-alpine

ARG NGINX_CONF=deploy/nginx/frontend.compose.conf
COPY ${NGINX_CONF} /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1