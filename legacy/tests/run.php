<?php

// Offline regression tests for legacy schedule parsers: replays recorded HTTP
// fixtures against legacy/module/<host>/index.php and diffs the normalized
// output with the golden snapshot. No network, no DB. Run inside the legacy
// container:
//   php tests/run.php [host]

require_once __DIR__ . '/harness.php';

$only_host = isset($argv[1]) ? $argv[1] : '';

$meta_files = array_merge(
    glob(__DIR__ . '/fixtures/*/meta.json'),
    glob(__DIR__ . '/fixtures/*/*/meta.json'),
);
if ($only_host) {
    $meta_files = array_filter($meta_files, function ($meta_file) use ($only_host) {
        $rel = substr(dirname($meta_file), strlen(__DIR__ . '/fixtures/'));
        return $rel === $only_host || basename($rel) === $only_host;
    });
    if (!$meta_files) {
        die("no fixture found for host '$only_host'\n");
    }
}
if (!$meta_files) {
    echo "no fixtures found under tests/fixtures/\n";
    exit(0);
}

$failures = 0;
foreach ($meta_files as $meta_file) {
    $fixture_dir = dirname($meta_file);
    $host = substr(dirname($meta_file), strlen(__DIR__ . '/fixtures/'));
    $expected_file = $fixture_dir . '/expected_contests.json';
    if (!file_exists($expected_file)) {
        echo fixture_colorize('FAIL', '31') . " $host (missing expected_contests.json)\n";
        $failures += 1;
        continue;
    }
    $expected = file_get_contents($expected_file);
    $code = fixture_exec_child(fixture_module_command($fixture_dir, 'replay', true), $stdout, $stderr);
    if ($code !== 0) {
        echo fixture_colorize('FAIL', '31') . " $host (exit code $code)\n";
        foreach (explode("\n", trim($stderr . "\n" . $stdout)) as $line) {
            echo "    $line\n";
        }
        $failures += 1;
        continue;
    }

    $actual_data = json_decode($stdout, true);
    $expected_data = json_decode($expected, true);
    if (!is_array($actual_data) || !is_array($expected_data)) {
        echo fixture_colorize('FAIL', '31') . " $host (invalid json output)\n";
        $failures += 1;
        continue;
    }

    if ($actual_data !== $expected_data) {
        echo fixture_colorize('FAIL', '31') . " $host (output mismatch)\n";
        fixture_print_diff(fixture_contests_to_json($expected_data), fixture_contests_to_json($actual_data));
        $failures += 1;
        continue;
    }
    echo fixture_colorize('PASS', '32') . " $host (" . count($expected_data) . " contests)\n";
}

echo ($failures ? $failures . ' of ' : 'all ') . count($meta_files) . ' fixture(s) ' . ($failures ? fixture_colorize('failed', '31') : fixture_colorize('passed', '32')) . "\n";
exit($failures ? 1 : 0);
