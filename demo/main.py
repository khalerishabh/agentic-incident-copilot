import importlib
import os

from demo.common.app_factory import create_app

SERVICE_NAME = os.getenv("SERVICE_NAME", "gateway")
module = importlib.import_module(f"demo.services.{SERVICE_NAME}")
app = create_app(SERVICE_NAME, module.router)
