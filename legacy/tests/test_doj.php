<?php

require_once __DIR__ . '/harness.php';

// Synthetic pages cover more than 20 upcoming/running contests and limited history.
$fixture_dir = __DIR__ . '/data/doj-pagination';
fixture_validate_recording($fixture_dir);
$meta = fixture_load_meta($fixture_dir);
$all_expected = json_decode(file_get_contents($fixture_dir . '/expected_contests.json'), true);
$cache_dir = fixture_materialize_http_cache($fixture_dir);
$replay_fixture_dir = sys_get_temp_dir() . '/clist-doj-parser-' . bin2hex(random_bytes(8));
mkdir($replay_fixture_dir);
try {
    foreach ([false, true] as $parse_full_list) {
        $meta['parse_full_list'] = $parse_full_list;
        file_put_contents($replay_fixture_dir . '/meta.json', fixture_contests_to_json($meta));
        $code = fixture_exec_child(fixture_module_command($replay_fixture_dir, 'replay', true, $cache_dir), $stdout, $stderr);
        if ($code !== 0) {
            throw new RuntimeException("DOJ pagination replay failed: $stderr");
        }
        $actual = json_decode($stdout, true);
        $expected = $all_expected;
        if (!$parse_full_list) {
            $n_ended = 0;
            $expected = array_filter($expected, function ($contest) use (&$n_ended) {
                return $contest['info']['parse']['status'] !== 'ENDED' || ++$n_ended <= 20;
            });
        }
        if (fixture_normalize_contests($actual) !== fixture_normalize_contests($expected)) {
            throw new RuntimeException('DOJ recent/full pagination or duration mismatch');
        }
    }
} finally {
    fixture_rmdir_recursive($cache_dir);
    fixture_rmdir_recursive($replay_fixture_dir);
}
echo "DOJ active/recent/full pagination, seconds precision, minute fallback, and fixed duration passed\n";
