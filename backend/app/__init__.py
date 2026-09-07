# 包级副作用：加载 backend/.env 到 os.environ（幂等、不覆盖已有变量）
from app import env  # noqa: F401
