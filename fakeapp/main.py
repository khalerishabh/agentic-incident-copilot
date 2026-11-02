import importlib
import os

from fakeapp.common.app_factory import create_app

SERVICE_NAME = os.getenv("SERVICE_NAME", "gateway")
module = importlib.import_module(f"fakeapp.services.{SERVICE_NAME}")
app = create_app(SERVICE_NAME, module.router)
