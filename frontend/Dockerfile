ARG DOCKERHUB_LIBRARY_PREFIX=
FROM ${DOCKERHUB_LIBRARY_PREFIX}node:22-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

ARG DOCKERHUB_LIBRARY_PREFIX=
FROM ${DOCKERHUB_LIBRARY_PREFIX}nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
