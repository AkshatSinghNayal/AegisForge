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

# This worker has broker access only: no database, API network, target URL or secret.
# Redis admission is fail-closed. Locks outlive the hard task limit and are never
# deleted by workers; duplicate deliveries cannot overlap or repeat a stage job.
app.conf.update(
    result_backend=settings.redis_url.get_secret_value(),
    task_ignore_result=False,
    result_expires=3600,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=3700 if settings.scanner_provider == "zap" else 20,
    task_soft_time_limit=3650 if settings.scanner_provider == "zap" else 15,
    broker_transport_options={"visibility_timeout": 60},
    broker_connection_timeout=2,
    task_publish_retry=False,
)


def execute_stage(payload: dict[str, object]) -> dict[str, object]:
    from celery.exceptions import Ignore
    from redis import Redis

    from aegis_api.scanner import MockScannerProvider, StageRequest, StageResult

    request = StageRequest.model_validate(payload)
    with Redis.from_url(
        settings.redis_url.get_secret_value(),
        socket_timeout=2,
        socket_connect_timeout=2,
    ) as broker:
        if not broker.set(f"scan-job:{request.job_id}", "claimed", nx=True, ex=7200):
            raise Ignore()
        lock_key = f"scan-worker:{request.scan_id}"
        duration = 3720 if settings.scanner_provider == "zap" else 25
        if not broker.set(lock_key, str(request.job_id), nx=True, ex=duration):
            raise Ignore()
        try:
            if settings.scanner_provider != "zap":
                return dict(
                    MockScannerProvider(settings)
                    .execute(request)
                    .model_dump(mode="json")
                )
            from cryptography.fernet import Fernet

            from aegis_api.zap.contracts import Execution
            from aegis_api.zap.provider import ZapScannerProvider
            from aegis_api.zap.runtime import DockerRuntime

            admitted = broker.set(
                "zap-global-slot", str(request.job_id), nx=True, ex=3720
            )
            if not admitted:
                return StageResult(
                    **request.model_dump(exclude={"demo", "execution"}),
                    status="provider_failed",
                ).model_dump(mode="json")
            runtime = None
            try:
                if request.execution is None:
                    raise ValueError("Execution unavailable")
                execution = Execution.model_validate_json(
                    Fernet(
                        settings.zap_dispatch_key.get_secret_value(),
                    ).decrypt(request.execution.get_secret_value().encode(), ttl=3600)
                )

                def alive() -> bool:
                    value = broker.get(f"zap-lease:{request.job_id}")
                    return bool(value == str(request.fence).encode())

                def emit(stage: object) -> None:
                    key = f"zap-progress:{request.job_id}"
                    with broker.pipeline() as pipe:
                        pipe.rpush(key, str(stage))
                        pipe.expire(key, 7200)
                        pipe.execute()

                runtime = DockerRuntime(settings, request.job_id, lambda: None)
                provider = ZapScannerProvider(settings, execution, runtime, alive, emit)
                runtime.check = provider.check
                runtime.reap()
                return provider.execute(request).model_dump(mode="json")
            except Exception:
                # Never send exceptions (including decrypted values or Docker output)
                # into Celery's result backend, task logs or API error messages.
                return StageResult(
                    **request.model_dump(exclude={"demo", "execution"}),
                    status="provider_failed",
                ).model_dump(mode="json")
            finally:
                if runtime is None or not runtime.resources or runtime.cleaned:
                    broker.eval(
                        "if redis.call('get',KEYS[1]) == ARGV[1] then "
                        "return redis.call('del',KEYS[1]) else return 0 end",
                        1,
                        "zap-global-slot",
                        str(request.job_id),
                    )
        finally:
            broker.eval(
                "if redis.call('get',KEYS[1]) == ARGV[1] then "
                "return redis.call('del',KEYS[1]) else return 0 end",
                1,
                lock_key,
                str(request.job_id),
            )


app.task(name="aegis.scan_stage")(execute_stage)
