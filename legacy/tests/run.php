<?php

// Offline regression tests for legacy schedule parsers: replays recorded HTTP
// fixtures against legacy/module/<host>/index.php and diffs the normalized
// output with the golden snapshot. No network, no DB. Run inside the legacy
// container:
//   php tests/run.php [host]

require_once __DIR__ . '/harness.php';

$only_host = isset($argv[1]) ? $argv[1] : '';

$direct_network_call = fixture_find_direct_network_call(dirname(__DIR__) . '/module');
if ($direct_network_call !== null) {
    fwrite(STDERR, "schedule modules must use curlexec() for HTTP: $direct_network_call\n");
    exit(1);
}

$meta_files = fixture_find_meta_files(__DIR__ . '/fixtures');
if ($only_host) {
    $meta_files = array_filter($meta_files, function ($meta_file) use ($only_host) {
        $meta = fixture_load_meta(dirname($meta_file));
        return $meta['host'] === $only_host;
    });
    if (!$meta_files) {
        fixture_fail("no fixture found for host '$only_host'");
    }
}
if (!$meta_files) {
    fwrite(STDERR, "no fixtures found under tests/fixtures/\n");
    exit(1);
}

$failures = 0;
foreach ($meta_files as $meta_file) {
    $fixture_dir = dirname($meta_file);
    $meta = fixture_load_meta($fixture_dir);
    $host = $meta['host'];
    $expected_file = $fixture_dir . '/expected_contests.json';
    if (!file_exists($expected_file)) {
        echo fixture_colorize('FAIL', '31') . " $host (missing expected_contests.json)\n";
        $failures += 1;
        continue;
    }
    try {
        fixture_validate_recording($fixture_dir);
        $cache_dir = fixture_materialize_http_cache($fixture_dir);
    } catch (RuntimeException $e) {
        echo fixture_colorize('FAIL', '31') . " $host ({$e->getMessage()})\n";
        $failures += 1;
        continue;
    }
    $expected = file_get_contents($expected_file);
    $code = fixture_exec_child(fixture_module_command($fixture_dir, 'replay', true, $cache_dir), $stdout, $stderr);
    fixture_rmdir_recursive($cache_dir);
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
