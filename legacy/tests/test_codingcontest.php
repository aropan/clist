<?php

require_once __DIR__ . '/harness.php';

$fixture_dir = __DIR__ . '/fixtures/codingcontest.org';
fixture_validate_recording($fixture_dir);
$cache_dir = fixture_materialize_http_cache($fixture_dir);
$cases = [
    ['42nd Coding Contest 2026', '42nd CLASSIC CCC', 'Nanofabricator', '42nd Coding Contest 2026. CLASSIC CCC. Nanofabricator'],
    ['42nd Coding Contest 2026', '42ND cOdInG School', null, '42nd Coding Contest 2026. School'],
    ['42nd Coding Contest 2026', '43rd Coding Contest', null, '42nd Coding Contest 2026. 43rd'],
    ['42nd Coding Contest 2026', '42ndish School', null, '42nd Coding Contest 2026. 42ndish School'],
    ['42nd Coding Contest 2026', '42nd Codingathon School', null, '42nd Coding Contest 2026. Codingathon School'],
    ['42nd Coding Contest 2026', '42nd School Contest 2026', null, '42nd Coding Contest 2026. School'],
    ['42nd Coding Contest 2026', '42ND CODING CONTEST 2026', null, '42nd Coding Contest 2026'],
    ['42nd Coding Contest 2026', '42nd Coding', null, '42nd Coding Contest 2026'],
    ['42nd Coding Contest 2026', 'Coding Contest', null, '42nd Coding Contest 2026'],
    ['  42nd Coding Contest 2026  ', " 42ND\tCoding  School  ", '  ', '42nd Coding Contest 2026. School'],
    ['Кубок Программирования 2026', 'кубок ПРОГРАММИРОВАНИЯ Школьники', null, 'Кубок Программирования 2026. Школьники'],
    ['29th Coding Contest 2018', '29th School Coding Contest 2018', 'Puzzle', '29th Coding Contest 2018. School. Puzzle'],
    ['Coding Contest', 'School', 'SCHOOL', 'Coding Contest. School'],
    ['Coding Contest', 'School', 'school Puzzle', 'Coding Contest. School. Puzzle'],
    ['Coding Contest', 'School', 'Puzzle SCHOOL', 'Coding Contest. School. Puzzle'],
    ['Coding Contest', 'School', 'School Puzzle Coding Contest', 'Coding Contest. School. Puzzle'],
    ['Coding Contest', 'School', 'School Coding Contest', 'Coding Contest. School'],
    ['Coding Contest', 'School', 'New Coding Contest Puzzle', 'Coding Contest. School. New Coding Contest Puzzle'],
    ['Coding Contest', 'School', 'School Codingathon', 'Coding Contest. School. Codingathon'],
    [null, 'School', 'Puzzle School', 'School. Puzzle'],
    ['', 'School', null, 'School'],
];

try {
    $responses = glob($cache_dir . '/*.html');
    if (count($responses) !== 1) {
        throw new RuntimeException('Expected one recorded contests page');
    }
    $response_file = $responses[0];
    list($headers, $body) = explode("\r\n\r\n", file_get_contents($response_file), 2);
    $response = json_decode($body, true);
    $source_contests = $response['content'];
    $response['content'] = [$source_contests[0]];

    foreach ($cases as [$edition_name, $contest_name, $game_name, $expected_title]) {
        $response['content'][0]['editionName'] = $edition_name;
        $response['content'][0]['name'] = $contest_name;
        $response['content'][0]['gameName'] = $game_name;
        file_put_contents($response_file, $headers . "\r\n\r\n" . json_encode($response));
        $code = fixture_exec_child(fixture_module_command($fixture_dir, 'replay', true, $cache_dir), $stdout, $stderr);
        if ($code !== 0) {
            throw new RuntimeException("Coding Contest title replay failed: $stderr");
        }
        $actual = json_decode($stdout, true);
        if (!is_array($actual) || count($actual) !== 1 || $actual[0]['title'] !== $expected_title) {
            throw new RuntimeException("Unexpected title for '$edition_name' / '$contest_name' / '$game_name': $stdout");
        }
    }

    // Split the archive into three pages even though the parser requests size=100.
    $pages = array_chunk($source_contests, 12);
    if (count($pages) < 3) {
        throw new RuntimeException('Expected enough archived contests to test pagination');
    }
    $meta = fixture_load_meta($fixture_dir);
    foreach ($pages as $page => $items) {
        $url = rtrim($meta['url'], '/') . "/api/contests?page=$page&size=100";
        $cache_name = $cache_dir . '/' . $meta['host'] . '-' . md5("GET\n$url\n");
        $response = [
            'content' => $items,
            'page' => $page,
            'totalPages' => count($pages),
            'totalElements' => count($source_contests),
            'size' => 12,
        ];
        file_put_contents($cache_name . '.html', $headers . "\r\n\r\n" . json_encode($response));
        file_put_contents($cache_name . '.meta.json', json_encode([
            'method' => 'GET',
            'url' => $url,
            'effective_url' => $url,
            'response_code' => 200,
        ]));
    }
    $code = fixture_exec_child(fixture_module_command($fixture_dir, 'replay', true, $cache_dir), $stdout, $stderr);
    if ($code !== 0) {
        throw new RuntimeException("Coding Contest pagination replay failed: $stderr");
    }
    $actual = json_decode($stdout, true);
    $expected = json_decode(file_get_contents($fixture_dir . '/expected_contests.json'), true);
    if ($actual !== $expected) {
        throw new RuntimeException('Paginated output differs from the complete archive');
    }
    $by_key = array_column($actual, null, 'key');
    $kinds = ['CLASSIC' => 'classic', 'SCHOOL' => 'school', 'AI' => 'ai'];
    foreach ($source_contests as $source_contest) {
        $parsed = $by_key[$source_contest['id']];
        if (
            $parsed['kind'] !== $kinds[$source_contest['contestType']]
            || $parsed['info']['parse'] !== fixture_normalize_value($source_contest)
            || $parsed['skip_check_time'] !== true
        ) {
            throw new RuntimeException('Contest kind, original API data, or historical import flag was not preserved');
        }
    }
    foreach ([0, 1] as $page) {
        $response = ['content' => [], 'page' => $page, 'totalPages' => 0];
        file_put_contents($response_file, $headers . "\r\n\r\n" . json_encode($response));
        $code = fixture_exec_child(fixture_module_command($fixture_dir, 'replay', true, $cache_dir), $stdout, $stderr);
        if ($code !== 0 || json_decode($stdout, true) !== []) {
            throw new RuntimeException("Empty or invalid pagination replay failed: $stderr");
        }
        if ($page === 1 && !str_contains($stderr, 'Unexpected contests response')) {
            throw new RuntimeException('Unexpected page number was not reported');
        }
    }
} finally {
    fixture_rmdir_recursive($cache_dir);
}

echo count($cases) . " title cases, full pagination, empty/invalid pages, kinds, and API data passed\n";
