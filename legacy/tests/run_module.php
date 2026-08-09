<?php

// Child process for schedule parser fixtures: runs one legacy/module parser
// against a fixture dir and prints the normalized $contests JSON to stdout.
// Module echoes are forwarded to stderr. Mode comes from the environment:
//   CURLEXEC_CACHE_MODE=record|replay CURLEXEC_CACHE_DIR=<materialized-cache> \
//     php tests/run_module.php <fixture_dir>

if (!in_array(getenv('CURLEXEC_CACHE_MODE'), ['record', 'replay'])) {
    fwrite(STDERR, "CURLEXEC_CACHE_MODE env must be 'record' or 'replay'\n");
    exit(1);
}
if (!getenv('CURLEXEC_CACHE_DIR') || !is_dir(getenv('CURLEXEC_CACHE_DIR'))) {
    fwrite(STDERR, "CURLEXEC_CACHE_DIR env must point to an existing directory\n");
    exit(1);
}

define('SKIP_DB_CONNECT', true);
chdir(dirname(__DIR__));
require_once dirname(__DIR__) . '/config.php';
require_once __DIR__ . '/harness.php';

if (count($argv) != 2 || !is_dir($argv[1])) {
    fwrite(STDERR, "usage: php tests/run_module.php <fixture_dir>\n");
    exit(1);
}

$meta = fixture_load_meta($argv[1]);
fixture_apply_globals($meta);

$contests = [];
ob_start();
try {
    include $meta['path'];
} finally {
    $buffer = ob_get_clean();
    if ($buffer !== false) {
        fwrite(STDERR, $buffer);
    }
}

$ignore_fields = isset($meta['ignore_fields']) ? $meta['ignore_fields'] : [];
echo fixture_contests_to_json(fixture_normalize_contests($contests, $ignore_fields));
