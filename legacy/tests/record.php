<?php

// Record an offline schedule parser fixture for one resource host.
// Fetches live pages through the module, snapshots the normalized $contests
// output, then immediately replays offline to verify the fixture is complete.
// Requires DB access and network; run inside the legacy container:
//   php tests/record.php <host> [--parse-full-list]

chdir(dirname(__DIR__));
require_once dirname(__DIR__) . '/config.php';
require_once __DIR__ . '/harness.php';

function fixture_remove_temporary_recording($tmp_dir)
{
    if (file_exists($tmp_dir)) {
        fixture_rmdir_recursive($tmp_dir);
    }
    $tmp_parent = dirname($tmp_dir);
    while ($tmp_parent !== __DIR__ . '/fixtures' && @rmdir($tmp_parent)) {
        $tmp_parent = dirname($tmp_parent);
    }
}

$args = array_slice($argv, 1);
$parse_full_list = in_array('--parse-full-list', $args);
$args = array_values(array_diff($args, ['--parse-full-list']));
if (count($args) != 1) {
    fixture_fail('usage: php tests/record.php <host> [--parse-full-list]');
}
$host = $args[0];
$fixture_component = fixture_resource_component($host);
$fixture_dir = __DIR__ . '/fixtures/' . $fixture_component;
$tmp_dir = __DIR__ . '/fixtures/.recording-' . $fixture_component;

$rows = $db->select('clist_resource', '*', "host = '" . $db->escapeString($host) . "'");
if (count($rows) != 1) {
    fixture_fail("expected exactly one resource for host '$host', got " . count($rows));
}
$resource = $rows[0];
if (empty($resource['path'])) {
    fixture_fail("resource '$host' has no module path; regexp-only resources are not supported");
}
$direct_network_call = fixture_find_direct_network_call(dirname(__DIR__) . '/module');
if ($direct_network_call !== null) {
    fixture_fail("schedule modules must use curlexec() for HTTP: $direct_network_call");
}

$existing_meta = [];
$existing_meta_file = $fixture_dir . '/meta.json';
if (file_exists($existing_meta_file)) {
    $decoded = json_decode(file_get_contents($existing_meta_file), true);
    if (is_array($decoded)) {
        $existing_meta = $decoded;
    }
}

$meta = [
    'host' => $resource['host'],
    'rid' => (int) $resource['id'],
    'path' => $resource['path'],
    'url' => $resource['url'],
    'parse_url' => empty($resource['parse_url']) ? $resource['url'] : $resource['parse_url'],
    'timezone' => $resource['timezone'],
    'api_url' => $resource['api_url'],
    'info' => json_decode($resource['info'], true),
    'parse_full_list' => $parse_full_list,
    'recorded_at' => date('Y-m-d H:i:s'),
];

foreach ($existing_meta as $key => $val) {
    if (!array_key_exists($key, $meta)) {
        $meta[$key] = $val;
    }
}

$record_modes = $parse_full_list ? [true] : [false, true];
foreach ($record_modes as $record_full_list) {
    $meta['parse_full_list'] = $record_full_list;
    $meta_issue = fixture_find_sensitive_json($meta, 'meta.json', $meta);
    if ($meta_issue !== null) {
        fixture_fail("refusing to record potentially sensitive metadata: $meta_issue");
    }

    if (file_exists($tmp_dir)) {
        fixture_rmdir_recursive($tmp_dir);
    }
    mkdir($tmp_dir . '/httpcache', 0777, true);
    file_put_contents($tmp_dir . '/meta.json', json_encode($meta, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) . "\n");

    echo 'recording ' . $host . ($record_full_list ? ' with full list' : '') . "...\n";
    $code = fixture_exec_child(fixture_module_command($tmp_dir, 'record', false), $stdout, $stderr);
    if ($code !== 0) {
        fwrite(STDERR, $stderr);
        fixture_fail("record run failed with exit code $code (temp dir kept: $tmp_dir)");
    }
    fixture_sanitize_recording($tmp_dir);
    $stdout = fixture_sanitize_public_text($stdout);
    $contests = json_decode($stdout, true);
    if (!is_array($contests)) {
        fwrite(STDERR, $stderr);
        fixture_fail("record run returned invalid JSON (temp dir kept: $tmp_dir)");
    }
    if ($contests) {
        break;
    }
    if (!$record_full_list) {
        echo "no contests found, retrying with full list...\n";
    }
}
if (!$contests) {
    fwrite(STDERR, $stderr);
    fixture_remove_temporary_recording($tmp_dir);
    fixture_fail('refusing to record fixture with 0 contests (temporary recording removed)');
}
file_put_contents($tmp_dir . '/expected_contests.json', $stdout);

try {
    fixture_validate_recording($tmp_dir);
} catch (RuntimeException $e) {
    fixture_remove_temporary_recording($tmp_dir);
    fixture_fail($e->getMessage() . ' (temporary recording removed)');
}

echo "verifying offline replay...\n";
$code = fixture_exec_child(fixture_module_command($tmp_dir, 'replay', true), $replay_stdout, $replay_stderr);
if ($code !== 0) {
    fwrite(STDERR, $replay_stderr);
    fixture_fail("replay verification failed with exit code $code (temp dir kept: $tmp_dir)");
}
if ($replay_stdout !== $stdout) {
    fixture_print_diff($stdout, $replay_stdout);
    fixture_fail("replay output differs from recorded output (temp dir kept: $tmp_dir)");
}

if (file_exists($fixture_dir)) {
    fixture_rmdir_recursive($fixture_dir);
}
$parent_dir = dirname($fixture_dir);
if (!is_dir($parent_dir)) {
    mkdir($parent_dir, 0777, true);
}
if (!rename($tmp_dir, $fixture_dir)) {
    fixture_fail("failed to move $tmp_dir into $fixture_dir");
}
fixture_remove_temporary_recording($tmp_dir);
fixture_chown_recursive(dirname($fixture_dir), fileowner(__DIR__), filegroup(__DIR__));

$n_responses = count(glob($fixture_dir . '/httpcache/*.html.gz'));
echo "recorded $host: " . count($contests) . " contests, $n_responses responses -> $fixture_dir\n";
