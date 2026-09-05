FROM node:24.14.0-alpine AS base
RUN npm install -g pnpm@11.19.0
WORKDIR /workspace
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile
COPY apps/web apps/web
FROM base AS dev
RUN chown -R node:node /workspace
EXPOSE 5173
USER node
CMD ["pnpm", "--filter", "@aegisforge/web", "dev"]
FROM base AS build
ARG VITE_SITE_URL=http://localhost:5173
ARG VITE_SECURITY_CONTACT=
ENV VITE_SITE_URL=$VITE_SITE_URL
ENV VITE_SECURITY_CONTACT=$VITE_SECURITY_CONTACT
RUN pnpm --filter @aegisforge/web build
FROM nginxinc/nginx-unprivileged:1.28.0-alpine AS production
COPY infra/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /workspace/apps/web/dist /usr/share/nginx/html
EXPOSE 8080
