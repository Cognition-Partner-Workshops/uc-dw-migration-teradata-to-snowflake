# Placeholder until the frontend workstream lands (multi-stage: node build -> nginx).
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
RUN mkdir -p /usr/share/nginx/html && echo '<h1>TD Migration Studio - UI coming soon</h1>' > /usr/share/nginx/html/index.html
