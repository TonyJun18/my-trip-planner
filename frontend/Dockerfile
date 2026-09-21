# ── my-trip-planner · 前端镜像 ───────────────────────────────
# 多阶段构建：Node 构建产物 → nginx 托管静态文件
# 构建：docker build -f frontend/Dockerfile -t my-trip-planner-frontend frontend
FROM node:22-alpine AS build

WORKDIR /app

# 先装依赖（利用层缓存）
COPY package.json package-lock.json ./
RUN npm ci

# 构建静态资源
COPY . .
RUN npm run build

# ── 运行阶段：nginx ──
FROM nginx:1.27-alpine

# 自定义 nginx 配置（SPA history 路由回退 + 反代 /api 到后端）
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

# 容器健康检查（docker-compose 依赖它判断前端就绪）
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1