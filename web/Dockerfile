# Sentinel web — Next.js 14 standalone build, served on Cloud Run.
#
# Build:   docker build -f web/Dockerfile -t sentinel-web ./web
# Run:     docker run --rm -p 3000:3000 -e PORT=3000 sentinel-web
# Deploy:  see docs/deploy.md
#
# The build needs ``NEXT_PUBLIC_API_BASE_URL`` baked in at compile time
# (Next inlines NEXT_PUBLIC_* env vars during ``next build``). Override
# at build via:
#   docker build --build-arg NEXT_PUBLIC_API_BASE_URL=https://api.example.com ...

ARG NODE_VERSION=20-alpine

# ── Stage 1: install ──────────────────────────────────────────────────
FROM node:${NODE_VERSION} AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --include=dev

# ── Stage 2: build ────────────────────────────────────────────────────
FROM node:${NODE_VERSION} AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ── Stage 3: runtime ──────────────────────────────────────────────────
FROM node:${NODE_VERSION} AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Standalone output ships the minimal Node server + deps actually used.
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000

CMD ["node", "server.js"]
