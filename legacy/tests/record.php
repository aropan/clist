<?php

// Record an offline schedule parser fixture for one resource host.
// Fetches live pages through the module, snapshots the normalized $contests
// output, then immediately replays offline to verify the fixture is complete.
// Requires DB access and network; run inside the legacy container:
//   php tests/record.php <host> [--parse-full-list]

chdir(dirname(__DIR__));
require_once dirname(__DIR__) . '/config.php';
require_once __DIR__ . '/harness.php';

$args = array_slice($argv, 1);
$parse_full_list = in_array('--parse-full-list', $args);
$args = array_values(array_diff($args, ['--parse-full-list']));
if (count($args) != 1) {
    die("usage: php tests/record.php <host> [--parse-full-list]\n");
}
$host = $args[0];

$rows = $db->select('clist_resource', '*', "host = '" . $db->escapeString($host) . "'");
if (count($rows) != 1) {
    die("expected exactly one resource for host '$host', got " . count($rows) . "\n");
}
$resource = $rows[0];
if (empty($resource['path'])) {
    die("resource '$host' has no module path; regexp-only resources are not supported\n");
}

$existing_meta = [];
$existing_meta_file = __DIR__ . '/fixtures/' . $host . '/meta.json';
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

if (preg_match_all('/"(\w*(?:key|token|secret|password|session|cookie)\w*)"\s*:/i', json_encode($meta['info']), $sensitive_matches)) {
    echo 'warning: meta info contains suspicious keys (' . implode(', ', array_unique($sensitive_matches[1])) . "), review meta.json before committing\n";
}

$fixture_dir = __DIR__ . '/fixtures/' . $host;
$tmp_dir = __DIR__ . '/fixtures/.recording-' . $host;
if (file_exists($tmp_dir)) {
    fixture_rmdir_recursive($tmp_dir);
}
mkdir($tmp_dir . '/httpcache', 0777, true);
file_put_contents($tmp_dir . '/meta.json', json_encode($meta, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) . "\n");

echo "recording $host...\n";
$code = fixture_exec_child(fixture_module_command($tmp_dir, 'record', false), $stdout, $stderr);
if ($code !== 0) {
    fwrite(STDERR, $stderr);
    die("record run failed with exit code $code (temp dir kept: $tmp_dir)\n");
}
$contests = json_decode($stdout, true);
if (!is_array($contests) || count($contests) == 0) {
    fwrite(STDERR, $stderr);
    die("refusing to record fixture with 0 contests (temp dir kept: $tmp_dir)\n");
}
file_put_contents($tmp_dir . '/expected_contests.json', $stdout);

echo "verifying offline replay...\n";
$code = fixture_exec_child(fixture_module_command($tmp_dir, 'replay', true), $replay_stdout, $replay_stderr);
if ($code !== 0) {
    fwrite(STDERR, $replay_stderr);
    die("replay verification failed with exit code $code (temp dir kept: $tmp_dir)\n");
}
if ($replay_stdout !== $stdout) {
    fixture_print_diff($stdout, $replay_stdout);
    die("replay output differs from recorded output (temp dir kept: $tmp_dir)\n");
}

if (file_exists($fixture_dir)) {
    fixture_rmdir_recursive($fixture_dir);
}
$parent_dir = dirname($fixture_dir);
if (!is_dir($parent_dir)) {
    mkdir($parent_dir, 0777, true);
}
if (!rename($tmp_dir, $fixture_dir)) {
    die("failed to move $tmp_dir into $fixture_dir\n");
}
$tmp_parent = dirname($tmp_dir);
while ($tmp_parent !== __DIR__ . '/fixtures' && @rmdir($tmp_parent)) {
    $tmp_parent = dirname($tmp_parent);
}
fixture_chown_recursive(dirname($fixture_dir), fileowner(__DIR__), filegroup(__DIR__));

$n_responses = count(glob($fixture_dir . '/httpcache/*.html.gz'));
echo "recorded $host: " . count($contests) . " contests, $n_responses responses -> $fixture_dir\n";
