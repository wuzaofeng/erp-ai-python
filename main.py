'''
Author: zack.wu zack.wu@zuru.com
Date: 2026-04-20 12:13:59
LastEditors: zack.wu zack.wu@zuru.com
LastEditTime: 2026-04-20 16:57:32
FilePath: \erp-ai-nodejsc:\WorkSpace\erp-ai-python\main.py
Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
'''
"""
ERP AI Python 服务入口 - 对应 src/index.ts
使用 FastAPI + uvicorn 替代 Express

启动方式：
  python main.py
  或
  uvicorn main:app --host 0.0.0.0 --port 3001 --reload
"""
import os
import sys

# 加载 .env 文件（需要 python-dotenv）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # 可选依赖，不影响启动

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from logger import logger
from db import init_db
from routes.ai import router as ai_router
from routes.knowledge import router as knowledge_router

# ===================== 应用初始化 =====================

app = FastAPI(
    title="ERP AI Assistant",
    description="ERP 系统智能数据查询 API（Python 版）",
    version="2.0.0",
)

# CORS 配置（与 Node.js 版保持一致）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],           # 生产环境按需收紧
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 数据库初始化（幂等，重复执行无副作用）
init_db()

# 注册路由
app.include_router(ai_router)
app.include_router(knowledge_router)


# ===================== 健康检查 =====================

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "erp-ai-python", "version": "2.0.0"}



@app.get("/")
def root():
    return {
        "message": "ERP AI Python 服务运行中",
        "docs": "/docs",
        "health": "/health",
    }


# ===================== 启动 =====================

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "3001"))
    host = os.getenv("HOST", "0.0.0.0")
    erp_url = os.getenv("ERP_BASE_URL", "(未配置)")
    default_model = os.getenv("DEFAULT_MODEL", "openai/gpt-4o-mini")
    encryption_secret = os.getenv("ENCRYPTION_SECRET", "")

    # 环境变量检查
    if not encryption_secret:
        logger.warn("Startup", "ENCRYPTION_SECRET 未设置，将使用默认值（不安全，仅用于开发）")

    logger.info("Startup", f"ERP AI Python 服务启动中...")
    logger.info("Startup", f"监听端口: {port}")
    logger.info("Startup", f"ERP 地址: {erp_url}")
    logger.info("Startup", f"默认模型: {default_model}")

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=os.getenv("ENV", "production") == "development",
        log_level="info",
    )
