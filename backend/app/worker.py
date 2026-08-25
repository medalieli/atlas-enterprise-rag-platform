from celery import Celery

from app.core.config import get_settings

settings = get_settings()
celery_app = Celery("rag_ingestion", broker=settings.redis_url)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    task_serializer="json",
    accept_content=["json"],
    result_backend=None,
)
celery_app.autodiscover_tasks(["app"])
