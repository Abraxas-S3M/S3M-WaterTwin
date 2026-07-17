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

# OIDC login config is baked into the static bundle at build time (Vite inlines
# VITE_* env). When these are empty the dashboard runs without a login gate,
# matching the API's WATERTWIN_AUTH_DISABLED dev bypass.
ARG VITE_KEYCLOAK_URL=""
ARG VITE_KEYCLOAK_REALM=""
ARG VITE_KEYCLOAK_CLIENT_ID=""
ENV VITE_KEYCLOAK_URL=$VITE_KEYCLOAK_URL \
    VITE_KEYCLOAK_REALM=$VITE_KEYCLOAK_REALM \
    VITE_KEYCLOAK_CLIENT_ID=$VITE_KEYCLOAK_CLIENT_ID

RUN npm run build

# --- Stage 2: serve the built SPA with nginx ------------------------------
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD wget -qO- http://localhost/ >/dev/null 2>&1 || exit 1
