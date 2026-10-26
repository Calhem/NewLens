# The NewsLens web image: builds the React app, then serves the static files with nginx.
# nginx also forwards /api/* to the API container, so the browser talks to one address.

FROM node:24.22.1-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# The unprivileged variant runs nginx as a non-root user, listening on port 8080.
FROM nginxinc/nginx-unprivileged:1.31.7-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 8080
