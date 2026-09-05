from celery import Celery
from celery.signals import setup_logging

from aegis_api.logging import configure_logging
from aegis_api.settings import WorkerSettings

settings = WorkerSettings()
app = Celery("aegisforge", broker=settings.redis_url.get_secret_value())
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
    worker_hijack_root_logger=False,
)


def configure_worker_logging(**kwargs: object) -> None:
    configure_logging(settings.log_level)


setup_logging.connect(configure_worker_logging, weak=False)
