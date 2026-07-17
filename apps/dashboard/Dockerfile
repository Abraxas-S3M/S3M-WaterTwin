# dashboard: the React/TypeScript operator Simulation Center UI.
#
# Two stages: build the Vite bundle with Node, then serve the static assets
# with nginx (which also proxies /api and /health to watertwin-api so the
# browser avoids CORS).
#
# Build context is apps/dashboard:
#   docker build -f apps/dashboard/Dockerfile -t dashboard apps/dashboard

# --- Stage 1: build the Vite/React bundle ---------------------------------
FROM node:22-alpine AS build
WORKDIR /build

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
RUN npm run build

# --- Stage 2: serve the built SPA with nginx ------------------------------
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD wget -qO- http://localhost/ >/dev/null 2>&1 || exit 1
