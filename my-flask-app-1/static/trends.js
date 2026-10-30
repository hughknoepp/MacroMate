// Draws the progress charts. The data comes from the page itself (<script id="trend-data">),
// and the dropdowns reload the page with the chosen statistic and period.
(function () {
    'use strict';

    var form = document.getElementById('trend-form');
    if (form) {
        form.querySelectorAll('select').forEach(function (select) {
            select.addEventListener('change', function () { form.submit(); });
        });
    }

    var dataElement = document.getElementById('trend-data');
    if (!dataElement || typeof Chart === 'undefined') { return; }
    var charts = JSON.parse(dataElement.textContent);

    function parseDay(iso) {              // "2026-10-30" -> a local date (not shifted by time zone)
        var parts = iso.split('-');
        return new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    }
    function shortDay(iso) {
        return parseDay(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    }
    function longDay(iso) {
        return parseDay(iso).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
    }
    function formatValue(value, unit) {
        var text = unit === 'kcal' ? Math.round(value).toLocaleString() : value.toLocaleString(undefined, { maximumFractionDigits: 1 });
        return text + ' ' + unit;
    }

    charts.forEach(function (chart) {
        var canvas = document.getElementById('chart-' + chart.slug);
        if (!canvas) { return; }
        var manyDays = chart.labels.length > 31;

        var datasets = [{
            label: chart.label,
            data: chart.values,
            borderColor: chart.color,
            backgroundColor: chart.color,
            borderWidth: 2,
            tension: manyDays ? 0 : 0.25,          // no smoothing on long periods, so the line never overshoots the data
            spanGaps: false,                       // a day with nothing logged is a break in the line
            pointRadius: manyDays ? 1.5 : 3,
            pointHoverRadius: 5
        }];
        if (chart.average !== null) {
            datasets.push({
                label: 'Average',
                data: chart.labels.map(function () { return chart.average; }),
                borderColor: '#888',
                borderDash: [6, 4],
                borderWidth: 1.5,
                pointRadius: 0,
                pointHoverRadius: 0
            });
        }

        new Chart(canvas, {
            type: 'line',
            data: { labels: chart.labels, datasets: datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            title: function (items) { return longDay(items[0].label); },
                            label: function (item) { return item.dataset.label + ': ' + formatValue(item.parsed.y, chart.unit); }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: {
                            maxRotation: 0,
                            autoSkip: true,
                            maxTicksLimit: 6,
                            callback: function (value) { return shortDay(this.getLabelForValue(value)); }
                        }
                    },
                    y: { beginAtZero: true, grace: '5%', ticks: { precision: 0 } }
                }
            }
        });
    });
})();
