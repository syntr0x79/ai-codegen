"""Factory of Code -- Worker Service.

Consumes jobs from RabbitMQ, executes agents, publishes results.
"""
import asyncio
import json
import logging
import os
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.config import Config
from src.db import Database
from src.shared.minio_client import MinIOClient
from src.shared.rabbitmq import (
    get_connection, declare_topology, publish_result,
    CANCEL_EXCHANGE, JOB_QUEUE,
)
from src.shared.models import JobMessage, ResultMessage
from worker.src.executor import JobExecutor
from worker.src.heartbeat import Heartbeat

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("worker")

WORKER_ID = f"worker-{uuid.uuid4().hex[:8]}"


async def main():
    config = Config()
    rabbitmq_url = os.environ.get("RABBITMQ_URL", "amqp://factory:factory@rabbitmq:5672/")

    # Database
    db = Database(config.database_url)
    for attempt in range(30):
        try:
            await db.init()
            break
        except Exception:
            if attempt < 29:
                await asyncio.sleep(2)
            else:
                raise
    log.info(f"Worker {WORKER_ID} connected to PostgreSQL")

    # MinIO
    minio = MinIOClient(config.minio_endpoint, config.minio_access_key, config.minio_secret_key)
    try:
        minio.ensure_bucket()
    except Exception as e:
        log.warning(f"MinIO init failed: {e}")
        minio = None

    # Restore credentials
    from src.shared.credentials import restore_all_credentials
    await restore_all_credentials(db.get_setting)

    # RabbitMQ
    rmq_conn = await get_connection(rabbitmq_url)
    channel = await rmq_conn.channel()
    await channel.set_qos(prefetch_count=1)
    await declare_topology(channel)
    log.info(f"Worker {WORKER_ID} connected to RabbitMQ")

    # Executor -- shared volume mounted at /app/data
    work_dir = Path("/app/data")
    work_dir.mkdir(parents=True, exist_ok=True)
    executor = JobExecutor(db, minio, work_dir)
    heartbeat = Heartbeat(db, WORKER_ID)

    # Cancel listener
    cancel_exchange = await channel.get_exchange(CANCEL_EXCHANGE)
    cancel_queue = await channel.declare_queue(exclusive=True)
    await cancel_queue.bind(cancel_exchange)

    async def on_cancel(message):
        async with message.process():
            data = json.loads(message.body)
            cancel_run_id = data.get("run_id")
            if cancel_run_id and executor.current_run_id == cancel_run_id:
                log.info(f"Cancel received for run {cancel_run_id}")
                executor.cancel_current()

    await cancel_queue.consume(on_cancel)

    # Job consumer
    job_queue = await channel.get_queue(JOB_QUEUE)

    async def on_job(message):
        async with message.process():
            data = json.loads(message.body)
            job = JobMessage(**data)
            log.info(f"Received job {job.job_id}: run={job.run_id} agent={job.agent_name}")

            # Refresh all credentials before each job (picks up changes from Settings)
            from src.shared.credentials import restore_all_credentials
            await restore_all_credentials(db.get_setting)

            from src.shared.token_refresh import refresh_token_if_needed
            await refresh_token_if_needed(db)

            # Start heartbeat
            await heartbeat.start(job.step_id)

            try:
                result = await executor.execute(job)
            finally:
                await heartbeat.stop()

            # Publish result
            await publish_result(channel, asdict(result))
            log.info(f"Job {job.job_id} completed: status={result.status}")

    await job_queue.consume(on_job)
    log.info(f"Worker {WORKER_ID} ready, waiting for jobs...")

    # Keep running
    try:
        await asyncio.Future()
    except asyncio.CancelledError:
        pass
    finally:
        await rmq_conn.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
