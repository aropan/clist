<?php

require_once __DIR__ . '/harness.php';

$fixture_dir = sys_get_temp_dir() . '/clist-codearena-' . bin2hex(random_bytes(8));
mkdir($fixture_dir . '/httpcache', 0777, true);
$meta = [
    'host' => 'codearena.uz', 'rid' => 1, 'path' => './module/codearena.uz/index.php',
    'url' => 'https://codearena.uz/contests/', 'parse_url' => 'https://codearena.uz/api/v1/contests/',
    'timezone' => 'UTC', 'recorded_at' => '2026-10-25 12:00:00', 'parse_full_list' => true,
];
$contest = [
    'id' => 21, 'title' => 'Marathon #3', 'url' => 'https://codearena.uz/contests/21/',
    'standings_url' => 'https://codearena.uz/contests/21/standings/',
    'start_time' => '2026-10-23T03:00:00Z', 'end_time' => '2026-10-26T03:00:00Z',
    'duration_minutes' => 4320, 'personal_minutes' => 120, 'kind' => 'marathon', 'rules' => 'cf',
    'is_rated' => false, 'authors' => ['c0de'], 'division' => null, 'n_participants' => 0,
];
$page = fn($rows, $number = 1, $count = null, $size = 200) => [
    'status' => 'ok', 'page' => $number, 'pageSize' => $size,
    'pagesCount' => (int) ceil(($count ?? count($rows)) / $size),
    'count' => $count ?? count($rows), 'data' => $rows,
];
$run = function ($pages, $full = true, $codes = []) use ($fixture_dir, &$meta) {
    $meta['parse_full_list'] = $full;
    file_put_contents($fixture_dir . '/meta.json', fixture_contests_to_json($meta));
    foreach ($pages as $index => $response) {
        $number = $index + 1;
        $status = $codes[$index] ?? 200;
        $url = $meta['parse_url'] . "?page=$number&page_size=200";
        $cache_name = $fixture_dir . '/httpcache/codearena.uz-' . md5("GET\n$url\n");
        file_put_contents($cache_name . '.html', "HTTP/1.1 $status Response\r\nContent-Type: application/json\r\n\r\n" . json_encode($response));
        file_put_contents($cache_name . '.meta.json', json_encode([
            'method' => 'GET', 'url' => $url, 'effective_url' => $url, 'response_code' => $status,
        ]));
    }
    $code = fixture_exec_child(fixture_module_command($fixture_dir, 'replay', true), $stdout, $stderr);
    if ($code !== 0) {
        throw new RuntimeException("CodeArena replay failed: $stderr");
    }
    return [json_decode($stdout, true), $stderr];
};
$check = function ($condition, $message) {
    if (!$condition) {
        throw new RuntimeException($message);
    }
};

try {
    [$actual, $stderr] = $run([$page([$contest], 1, 2, 1), $page([array_replace($contest, ['id' => 20])], 2, 2, 1)]);
    $check(count($actual) === 2 && $stderr === '', 'Complete pagination failed');
    $check(array_column($actual, 'key') === ['20', '21'], 'Stable string IDs failed');
    $parsed = $actual[1];
    $check($parsed['duration_in_secs'] === 7200, 'Personal duration lost');
    $check(strtotime($parsed['end_time']) - strtotime($parsed['start_time']) === 259200, 'Availability window lost');
    $check($parsed['info']['parse'] === fixture_normalize_value($contest), 'Raw metadata lost');
    $check($parsed['info']['writers'] === ['c0de'] && $parsed['is_rated'] === 'false', 'Writers or false rating lost');
    $check($parsed['skip_check_time'] === true, 'Full-list age bypass lost');
    foreach (['icpc' => 'icpc', 'cf' => 'cf', 'score' => 'scoring'] as $rule => $kind) {
        [$actual] = $run([$page([array_replace($contest, ['rules' => $rule, 'personal_minutes' => null])])], false);
        $check($actual[0]['standings_kind'] === $kind, 'Scoring kind mismatch');
        $check($actual[0]['duration_in_secs'] === 259200 && $actual[0]['skip_check_time'] === false, 'Untimed marathon or normal age filter mismatch');
    }
    [$actual, $stderr] = $run([$page([])]);
    $check($actual === [] && $stderr === '', 'Valid empty page failed');
    foreach ([null, [], ['status' => 'ok'], array_replace($page([]), ['status' => 'error'])] as $response) {
        [$actual, $stderr] = $run([$response]);
        $check($actual === [] && $stderr !== '', 'Failed API response accepted');
    }
    [$actual, $stderr] = $run([$page([array_replace($contest, ['rules' => 'unknown'])])]);
    $check($actual === [] && str_contains($stderr, "Unknown rules 'unknown' for contest 21"), 'Unknown rules were not reported');
    [$actual, $stderr] = $run([$page([$contest], 1, 2, 1), null]);
    $check($actual === [] && $stderr !== '', 'Later-page failure published a partial catalogue');
    [$actual, $stderr] = $run([$page([$contest], 1, 2, 1), $page([array_replace($contest, ['id' => 22])], 2, 2, 1)], true, [200, 429]);
    $check($actual === [] && $stderr !== '', 'Throttled page published a partial catalogue');
} finally {
    fixture_rmdir_recursive($fixture_dir);
}
echo "CodeArena pagination, failures, metadata, rules and marathon timing passed\n";
