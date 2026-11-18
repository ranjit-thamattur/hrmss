# Hotel Vivek web image = hrms-core React app built with this folder as the tenant, served by nginx.
# Build context is the services/ folder:  docker build -f hotel_vivek_frontend/Dockerfile services
FROM node:20-alpine AS build
WORKDIR /src/core
COPY hrms-core/frontend/package*.json ./
RUN npm install --no-audit --no-fund
COPY hrms-core/frontend/ ./
COPY hotel_vivek_frontend/ /src/tenant/
ARG VITE_HIDE_DEMO_HINT=false
ENV TENANT_FRONTEND_DIR=/src/tenant VITE_HIDE_DEMO_HINT=${VITE_HIDE_DEMO_HINT}
RUN npm run build

FROM nginx:1.27-alpine
COPY hrms-core/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/core/dist /usr/share/nginx/html
EXPOSE 80
