"""Run with:  python -m unittest discover -v   (from the project folder)"""
import threading
import unittest

import requests

from pipeline import RequestPipeline, is_transient


def http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f'{status} error', response=response)


class Flaky:
    """Fails with the given errors in order, then returns `value`."""
    def __init__(self, errors, value='ok'):
        self.errors, self.value, self.calls = list(errors), value, 0

    def __call__(self, results):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return self.value


class OrderingTests(unittest.TestCase):
    def test_each_step_sees_inputs_and_earlier_results(self):
        pipeline = (RequestPipeline()
                    .step('details', lambda r: {'id': r['fdc_id'], 'name': 'apple'})
                    .step('label', lambda r: f"{r['details']['name']}#{r['details']['id']}"))
        outcome = pipeline.run(fdc_id=7)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome['label'], 'apple#7')
        self.assertEqual(list(outcome.results), ['details', 'label'])

    def test_steps_run_in_the_order_they_were_added(self):
        order = []
        pipeline = RequestPipeline()
        for name in 'abcd':
            pipeline.step(name, lambda r, n=name: order.append(n))
        pipeline.run()
        self.assertEqual(order, ['a', 'b', 'c', 'd'])

    def test_empty_pipeline_succeeds(self):
        self.assertTrue(RequestPipeline().run(x=1).ok)

    def test_a_step_cannot_change_what_later_steps_see(self):
        def meddle(results):
            results['fdc_id'] = 'tampered'
            results['extra'] = 1
        pipeline = (RequestPipeline().step('meddle', meddle)
                    .step('check', lambda r: (r['fdc_id'], 'extra' in r)))
        self.assertEqual(pipeline.run(fdc_id=5)['check'], (5, False))


class FailureTests(unittest.TestCase):
    def test_first_failure_stops_the_run_and_keeps_earlier_results(self):
        later = []
        boom = ValueError('boom')
        pipeline = (RequestPipeline()
                    .step('one', lambda r: 1)
                    .step('two', lambda r: (_ for _ in ()).throw(boom))
                    .step('three', lambda r: later.append('ran')))
        outcome = pipeline.run()
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.failed_step, 'two')
        self.assertIs(outcome.error, boom)
        self.assertEqual(outcome.results, {'one': 1})
        self.assertEqual(later, [])

    def test_a_failure_in_the_first_step_runs_nothing_else(self):
        second = Flaky([])
        outcome = RequestPipeline().step('a', Flaky([ValueError()])).step('b', second).run()
        self.assertEqual((outcome.failed_step, second.calls), ('a', 0))


class RetryTests(unittest.TestCase):
    def pipeline(self, step, retries, sleeps):
        return RequestPipeline(backoff_seconds=0.25, sleep=sleeps.append).step('fetch', step, retries=retries)

    def test_transient_error_is_retried_until_it_succeeds(self):
        sleeps = []
        step = Flaky([requests.ConnectionError(), requests.Timeout()], value='data')
        outcome = self.pipeline(step, 2, sleeps).run()
        self.assertEqual((outcome.ok, outcome['fetch'], step.calls), (True, 'data', 3))
        self.assertEqual(sleeps, [0.25, 0.5])  # waits a little longer each time

    def test_gives_up_after_the_allowed_retries(self):
        step = Flaky([requests.ConnectionError()] * 5)
        outcome = self.pipeline(step, 2, []).run()
        self.assertEqual((outcome.ok, step.calls), (False, 3))  # first try + 2 retries

    def test_no_retries_unless_asked_for(self):
        step = Flaky([requests.ConnectionError()])
        self.assertFalse(self.pipeline(step, 0, []).run().ok)
        self.assertEqual(step.calls, 1)

    def test_errors_that_will_not_fix_themselves_are_not_retried(self):
        for error in (http_error(404), http_error(400), ValueError('bad data'), KeyError('x')):
            step = Flaky([error])
            outcome = self.pipeline(step, 3, []).run()
            self.assertEqual((outcome.ok, step.calls), (False, 1), msg=repr(error))

    def test_rate_limit_and_server_errors_are_retried(self):
        for status in (429, 500, 502, 503, 504):
            step = Flaky([http_error(status)])
            self.assertTrue(self.pipeline(step, 1, []).run().ok, msg=status)
            self.assertEqual(step.calls, 2)

    def test_is_transient(self):
        self.assertTrue(is_transient(requests.ConnectionError()))
        self.assertTrue(is_transient(http_error(503)))
        self.assertFalse(is_transient(http_error(404)))
        self.assertFalse(is_transient(requests.HTTPError('no response attached')))
        self.assertFalse(is_transient(ValueError()))


class SetupTests(unittest.TestCase):
    def test_duplicate_step_names_are_rejected(self):
        with self.assertRaises(ValueError):
            RequestPipeline().step('a', lambda r: 1).step('a', lambda r: 2)

    def test_inputs_cannot_shadow_step_names(self):
        with self.assertRaises(ValueError):
            RequestPipeline().step('details', lambda r: 1).run(details='x')


class SharingTests(unittest.TestCase):
    def test_one_pipeline_handles_many_simultaneous_runs_without_mixing_them_up(self):
        pipeline = (RequestPipeline()
                    .step('double', lambda r: r['n'] * 2)
                    .step('plus_one', lambda r: r['double'] + 1))
        answers, errors = {}, []

        def work(n):
            try:
                answers[n] = pipeline.run(n=n)['plus_one']
            except Exception as error:  # pragma: no cover
                errors.append(error)

        threads = [threading.Thread(target=work, args=(n,)) for n in range(200)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(errors, [])
        self.assertEqual(answers, {n: n * 2 + 1 for n in range(200)})


if __name__ == '__main__':
    unittest.main()
