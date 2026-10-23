# Next.js standalone image. Build with context web/:  docker buildx build -t <repo> web
# No secrets are baked in: nothing here reads NEXT_PUBLIC_* or any server secret at build time;
# server configuration is read from the runtime environment.

FROM node:22.15.0-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci


FROM node:22.15.0-bookworm-slim AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npx next build


FROM node:22.15.0-bookworm-slim AS runtime

ARG VERSION=0.0.0
ARG GIT_SHA=unknown
LABEL org.opencontainers.image.title="cashapp-web" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}"

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin nextjs

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

WORKDIR /app

COPY --from=builder --chown=10001:10001 /app/public ./public
COPY --from=builder --chown=10001:10001 /app/.next/standalone ./
COPY --from=builder --chown=10001:10001 /app/.next/static ./.next/static

USER 10001

EXPOSE 3000

CMD ["node", "server.js"]
