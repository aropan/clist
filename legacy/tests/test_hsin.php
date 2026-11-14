<?php

require_once __DIR__ . '/harness.php';

$fixture_dir = __DIR__ . '/fixtures/hsin.hr__coci';
fixture_validate_recording($fixture_dir);
$expected = json_decode(file_get_contents($fixture_dir . '/expected_contests.json'), true);
$cache_dir = fixture_materialize_http_cache($fixture_dir);
$responses = [];
foreach (glob($cache_dir . '/*.html') as $file) {
    $responses[$file] = file_get_contents($file);
}
$cases = [
    ['COCI $1/$2', true],
    ['CROATIAN OPEN COMPETITION IN INFORMATICS $1 - $2', true],
    ['COCI 1$1/$2', false],
    ['COCI $1/${2}0', false],
    ['COCI $1d$2', false],
    ['COCI $1/$2 extra', false],
    ['COCI $1/2099', false],
    ['ARCHIVE $1/$2', false],
];

try {
    foreach ($cases as [$heading, $valid]) {
        foreach ($responses as $file => $response) {
            // A real CF-Ray that the old parser mistook for season 3298-6513.
            $response = substr_replace($response, "CF-Ray: a5a953298d651336-FRA\r\n", strpos($response, "\r\n") + 2, 0);
            $response = preg_replace('#>COCI ([0-9]{4})/([0-9]{4})</div>#', '>' . $heading . '</div>', $response, -1, $count);
            if ($count !== 1) {
                throw new RuntimeException('Expected one season heading per COCI page');
            }
            file_put_contents($file, $response);
        }
        $code = fixture_exec_child(fixture_module_command($fixture_dir, 'replay', true, $cache_dir), $stdout, $stderr);
        if ($code !== 0 || $stderr !== '' || json_decode($stdout, true) !== ($valid ? $expected : [])) {
            throw new RuntimeException("Unexpected COCI season parsing for '$heading': $stderr $stdout");
        }
    }
} finally {
    fixture_rmdir_recursive($cache_dir);
}

echo "COCI HTTP headers, legacy headings, separators, year boundaries and consecutive years passed\n";
