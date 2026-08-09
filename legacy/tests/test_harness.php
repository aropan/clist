<?php

require_once __DIR__ . '/harness.php';

$tests = 0;

function fixture_test_assert($condition, $message)
{
    global $tests;
    $tests += 1;
    if (!$condition) {
        throw new RuntimeException($message);
    }
}

$normalized = fixture_normalize_contests([
    ['title' => 'B', 'nested' => ['z' => 1, 'a' => 2]],
    ['title' => 'A', 'nested' => ['z' => 1, 'a' => 2], 'ignored' => time()],
], ['ignored']);
fixture_test_assert($normalized[0]['title'] === 'A', 'contests must be sorted deterministically');
fixture_test_assert(array_keys($normalized[1]['nested']) === ['a', 'z'], 'object keys must be sorted recursively');
fixture_test_assert(
    fixture_resource_component('example.com/path_with_underscore') === 'example.com__path%5Fwith%5Funderscore',
    'resource fixture components must encode slashes without creating nested directories',
);
fixture_test_assert(
    fixture_resource_component('example.com__path/with_underscore') ===
        'example.com%5F%5Fpath__with%5Funderscore',
    'literal underscores must not collide with encoded slashes',
);

fixture_test_assert(fixture_is_sensitive_field_name('LEETCODE_SESSION'), 'session metadata must be sensitive');
fixture_test_assert(!fixture_is_sensitive_field_name('testSessionHandle'), 'technical session handles must be allowed');
putenv('FIXTURE_TEST_API_TOKEN=fixture-secret-value');
fixture_test_assert(
    fixture_validate_content('{"affiliation":"Bearer University"}', 'response.json', []) === null,
    'ordinary public text must not look like an authorization header',
);
fixture_test_assert(
    fixture_validate_content('{"payload":"fixture-secret-value"}', 'response.json', []) !== null,
    'known secret environment values must be rejected under ordinary field names',
);
fixture_test_assert(
    fixture_validate_content('{"accessToken":"not-a-real-access-token"}', 'response.json', []) !== null,
    'sensitive JSON fields must be rejected',
);
fixture_test_assert(
    fixture_validate_content('{"filledPassword":false}', 'response.json', []) === null,
    'public boolean credential flags must be allowed',
);
fixture_test_assert(
    fixture_validate_content("HTTP/1.1 200 OK\r\nSet-Cookie: sid=not-a-real-cookie\r\n\r\n", 'response.html', []) !== null,
    'server-issued cookies must be rejected',
);
fixture_test_assert(
    fixture_validate_content("HTTP/1.1 200 OK\r\nSet-Cookie: sid=<redacted>; Path=/\r\n\r\n", 'response.html', []) === null,
    'redacted cookie placeholders must be allowed',
);
fixture_test_assert(
    fixture_validate_content('https://fixture-user:not-a-real-password@example.com/', 'response.html', []) !== null,
    'credentials embedded in URLs must be rejected',
);
$google_api_key = 'AIza' . str_repeat('x', 35);
$public_text = '{"contact":"contact@example.com","phone":"+123 456 7890",' .
    '"testSessionHandle":"public-test-session-handle","key":"' . $google_api_key . '"}';
fixture_test_assert(
    fixture_sanitize_public_text($public_text) ===
        '{"contact":"<redacted-email>","phone":"<redacted-phone>",' .
        '"testSessionHandle":"<redacted-test-session-handle>","key":"<redacted-google-api-key>"}',
    'email addresses, phone numbers, browser API keys, and test session handles must be redacted',
);
fixture_test_assert(
    fixture_sanitize_public_text('tel:+1234567890') === 'tel:<redacted-phone>',
    'telephone links must be redacted',
);
fixture_test_assert(
    fixture_sanitize_public_text('calendar@group.calendar.google.com') === 'calendar@group.calendar.google.com',
    'public Google Calendar identifiers must be preserved',
);
fixture_test_assert(
    fixture_validate_content($public_text, 'response.html', []) !== null,
    'unsanitized public contact data must be rejected',
);
$gzip = gzencode('deterministic fixture', 9);
fixture_test_assert(substr($gzip, 4, 4) === "\0\0\0\0", 'gzip fixtures must not contain the current timestamp');

$allowed_meta = [
    'allowed_sensitive_fields' => [
        ['file' => 'response.json', 'path' => '$.technical.session'],
    ],
];
fixture_test_assert(
    fixture_validate_content('{"technical":{"session":"public-id"}}', 'response.json', $allowed_meta) === null,
    'narrow per-file sensitive field exceptions must be supported',
);

$fixtures_dir = sys_get_temp_dir() . '/clist-schedule-fixtures-' . bin2hex(random_bytes(8));
$fixture_dir = $fixtures_dir . '/' . fixture_resource_component('example.com');
mkdir($fixture_dir . '/httpcache', 0777, true);
try {
    $meta = [
        'host' => 'example.com',
        'rid' => 1,
        'path' => 'module/example.com/index.php',
        'url' => 'https://example.com/',
        'parse_url' => 'https://example.com/contests',
        'timezone' => 'UTC',
        'recorded_at' => '2026-08-06 00:00:00',
    ];
    file_put_contents($fixture_dir . '/meta.json', fixture_contests_to_json($meta));
    file_put_contents($fixture_dir . '/expected_contests.json', "[]\n");
    file_put_contents($fixture_dir . '/httpcache/safe.html.gz', gzencode('<html>public schedule</html>', 9));
    fixture_test_assert(count(fixture_find_meta_files($fixtures_dir)) === 1, 'canonical fixture directories must be discovered');
    fixture_validate_recording($fixture_dir);
    fixture_test_assert(true, 'safe fixture must pass validation');

    file_put_contents(
        $fixture_dir . '/httpcache/sensitive.html.gz',
        gzencode('{"client_secret":"not-a-real-client-secret"}', 9),
    );
    try {
        fixture_validate_recording($fixture_dir);
        fixture_test_assert(false, 'sensitive fixture must fail validation');
    } catch (RuntimeException $e) {
        fixture_test_assert(
            strpos($e->getMessage(), 'httpcache/sensitive.html.gz') !== false,
            'validation failure must identify the unsafe file',
        );
    }
} finally {
    fixture_rmdir_recursive($fixtures_dir);
}

$direct_network_call = fixture_find_direct_network_call(dirname(__DIR__) . '/module');
fixture_test_assert($direct_network_call === null, "schedule modules must not bypass curlexec(): $direct_network_call");

echo "all $tests schedule fixture harness test(s) passed\n";
