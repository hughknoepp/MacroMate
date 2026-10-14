"""Run dependent requests in order, passing each step's result on to the next.

Some lookups can't start until an earlier one has finished: fetching a food's nutrition
needs the fdcId, and reading the nutrients needs the fetched record. A RequestPipeline
runs such steps strictly one after another. Each step receives everything produced so far,
the first failure stops the run, and the result says which step failed and why.

    pipeline = (RequestPipeline()
                .step('details', lambda r: get_food_details(r['fdc_id']), retries=2)
                .step('nutrients', lambda r: extract_nutrients(r['details'])))

    outcome = pipeline.run(fdc_id=454004)
    if outcome.ok:
        outcome['nutrients']
    else:
        outcome.failed_step, outcome.error

A pipeline holds no per-run state, so one instance can be built once and reused by any
number of requests, including at the same time.
"""
import time
from dataclasses import dataclass, field

import requests

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def is_transient(error):
    """True for failures worth retrying: network trouble, timeouts, rate limits, server errors."""
    if isinstance(error, (requests.ConnectionError, requests.Timeout)):
        return True
    if isinstance(error, requests.HTTPError) and error.response is not None:
        return error.response.status_code in RETRYABLE_STATUS_CODES
    return False


@dataclass
class PipelineResult:
    """What a run produced: every completed step's value, plus the failure if there was one."""
    results: dict = field(default_factory=dict)
    failed_step: str = None
    error: Exception = None

    @property
    def ok(self):
        return self.failed_step is None

    def __getitem__(self, name):
        return self.results[name]


class RequestPipeline:
    def __init__(self, backoff_seconds=0.25, sleep=time.sleep):
        self._steps = []
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep

    def step(self, name, func, retries=0):
        """Add a step. `func` gets a dict of the run's inputs and earlier steps' results.

        A step that raises fails the run. If `retries` is set, transient errors
        (see is_transient) are retried that many times, waiting a little longer each time.
        Returns the pipeline so calls can be chained.
        """
        if any(existing == name for existing, _, _ in self._steps):
            raise ValueError(f'duplicate step name: {name!r}')
        self._steps.append((name, func, retries))
        return self

    def run(self, **inputs):
        """Run the steps in order. Never raises for a step failure; check `.ok` on the result."""
        step_names = {name for name, _, _ in self._steps}
        clash = step_names & set(inputs)
        if clash:
            raise ValueError(f'inputs share names with steps: {sorted(clash)}')

        context = dict(inputs)  # inputs plus each finished step's value
        outcome = PipelineResult()
        for name, func, retries in self._steps:
            try:
                value = self._call(func, context, retries)
            except Exception as error:
                outcome.failed_step = name
                outcome.error = error
                return outcome
            context[name] = value
            outcome.results[name] = value
        return outcome

    def _call(self, func, context, retries):
        attempt = 0
        while True:
            try:
                return func(dict(context))  # a copy, so a step can't change what later steps see
            except Exception as error:
                if attempt >= retries or not is_transient(error):
                    raise
                attempt += 1
                self._sleep(self._backoff_seconds * attempt)
