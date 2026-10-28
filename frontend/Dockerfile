# Build the SPA, then serve it from the Caddy image (see docker-compose.prod.yml).
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG VITE_API_URL=/api/v1
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build
FROM alpine:3.20
COPY --from=build /app/dist /srv
