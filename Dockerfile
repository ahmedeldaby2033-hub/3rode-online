# 3rde.online — static site on nginx (Coolify / any Docker host)
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY site/ /usr/share/nginx/html/
COPY admin/index.html /usr/share/nginx/html/admin/index.html
EXPOSE 80
