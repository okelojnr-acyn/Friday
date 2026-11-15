# Friday's web app for self-hosted installs (deploy/compose.yml): the
# built SPA served by Caddy. The kernel address is not baked in: the
# entrypoint writes /config.js from FRIDAY_KERNEL_URL at start, so one
# image serves any domain.
FROM node:20-alpine AS build
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ .
RUN npm run build

FROM caddy:2.11-alpine
COPY --from=build /src/web/dist /srv
COPY infra/web.Caddyfile /etc/caddy/Caddyfile
COPY infra/web-entrypoint.sh /usr/local/bin/web-entrypoint
RUN chmod +x /usr/local/bin/web-entrypoint
EXPOSE 80
ENTRYPOINT ["web-entrypoint"]
