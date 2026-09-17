"""RabbitMQ connection helpers and queue declarations."""
from __future__ import annotations

import json
import logging

import aio_pika

logger = logging.getLogger(__name__)

# Queue/exchange names
JOB_EXCHANGE = "factory.jobs"
JOB_QUEUE = "factory.job_queue"
RESULT_EXCHANGE = "factory.results"
RESULT_QUEUE = "factory.results"
CANCEL_EXCHANGE = "factory.cancel"


async def get_connection(url: str) -> aio_pika.abc.AbstractRobustConnection:
    """Create a robust RabbitMQ connection with auto-reconnect."""
    return await aio_pika.connect_robust(url)


async def declare_topology(channel: aio_pika.abc.AbstractChannel) -> None:
    """Declare all exchanges and queues."""
    # Job exchange + queue
    job_exchange = await channel.declare_exchange(
        JOB_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True,
    )
    job_queue = await channel.declare_queue(JOB_QUEUE, durable=True)
    await job_queue.bind(job_exchange, routing_key=JOB_QUEUE)

    # Result exchange + queue
    result_exchange = await channel.declare_exchange(
        RESULT_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True,
    )
    result_queue = await channel.declare_queue(RESULT_QUEUE, durable=True)
    await result_queue.bind(result_exchange, routing_key=RESULT_QUEUE)

    # Cancel exchange (fanout -- broadcast to all workers)
    await channel.declare_exchange(
        CANCEL_EXCHANGE, aio_pika.ExchangeType.FANOUT, durable=True,
    )

    logger.info("RabbitMQ topology declared")


async def publish_job(channel: aio_pika.abc.AbstractChannel, job: dict) -> None:
    """Publish a job message to the job queue."""
    exchange = await channel.get_exchange(JOB_EXCHANGE)
    await exchange.publish(
        aio_pika.Message(
            body=json.dumps(job).encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        ),
        routing_key=JOB_QUEUE,
    )


async def publish_result(channel: aio_pika.abc.AbstractChannel, result: dict) -> None:
    """Publish a result message."""
    exchange = await channel.get_exchange(RESULT_EXCHANGE)
    await exchange.publish(
        aio_pika.Message(
            body=json.dumps(result).encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        ),
        routing_key=RESULT_QUEUE,
    )


async def publish_cancel(channel: aio_pika.abc.AbstractChannel, run_id: int) -> None:
    """Broadcast cancel to all workers."""
    exchange = await channel.get_exchange(CANCEL_EXCHANGE)
    await exchange.publish(
        aio_pika.Message(body=json.dumps({"run_id": run_id}).encode()),
        routing_key="",
    )
