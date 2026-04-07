#!/usr/bin/env python3
import argparse
import random
import time

from prometheus_remote_writer import RemoteWriter


def build_series(metric_name: str, labels: dict, value: float):
    metric_labels = {"__name__": metric_name, **labels}
    return {
        "metric": metric_labels,
        "values": [value],
        "timestamps": [int(time.time() * 1000)],
    }


def main():
    parser = argparse.ArgumentParser(description="Write demo metrics via Prometheus remote_write")
    parser.add_argument("--url", default="http://localhost:19090/api/v1/write")
    parser.add_argument("--batches", type=int, default=5)
    args = parser.parse_args()

    writer = RemoteWriter(url=args.url)

    base_labels = {"service": "oncall", "env": "local", "instance": "macbook"}
    for i in range(1, args.batches + 1):
        qps = round(random.uniform(10, 35), 2)
        latency = round(random.uniform(20, 120), 2)
        err = round(random.uniform(0, 3), 3)

        metrics = [
            build_series("demo_oncall_qps", base_labels, qps),
            build_series(
                "demo_oncall_latency_ms",
                {**base_labels, "api": "/open-api/events"},
                latency,
            ),
            build_series("demo_oncall_error_ratio", base_labels, err),
        ]

        result = writer.send(metrics)
        status = result.last_response.status_code if result.last_response is not None else "n/a"
        print(
            f"push#{i} -> HTTP {status} "
            f"(qps={qps} latency={latency} err={err}, samples={result.samples_sent})"
        )
        time.sleep(1)


if __name__ == "__main__":
    main()

