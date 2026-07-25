<?php

// Shared helpers for offline schedule parser fixtures (tests/record.php,
// tests/run.php, tests/run_module.php). Pure functions only: this file must
// stay side-effect free on include and must not require config.php.

function fixture_load_meta($fixture_dir)
{
    $meta_file = $fixture_dir . '/meta.json';
    if (!file_exists($meta_file)) {
        die("missing $meta_file\n");
    }
    $meta = json_decode(file_get_contents($meta_file), true);
    if (!is_array($meta)) {
        die("invalid json in $meta_file\n");
    }
    foreach (['host', 'rid', 'path', 'url', 'parse_url', 'timezone', 'recorded_at'] as $field) {
        if (!isset($meta[$field])) {
            die("missing '$field' in $meta_file\n");
        }
    }
    return $meta;
}

function fixture_apply_globals($meta)
{
    global $HOST_URL, $URL, $HOST, $RID, $TIMEZONE, $INFO, $API_URL, $PARSE_FULL_LIST, $RESOURCE_URL, $RESOURCE_ICON_URL;
    $HOST_URL = $meta['url'];
    $URL = strtr($meta['parse_url'], ['${YEAR}' => date('Y')]);
    $HOST = $meta['host'];
    $RID = $meta['rid'];
    $TIMEZONE = $meta['timezone'];
    $INFO = isset($meta['info']) ? $meta['info'] : [];
    $API_URL = isset($meta['api_url']) ? $meta['api_url'] : null;
    $PARSE_FULL_LIST = !empty($meta['parse_full_list']);
    $RESOURCE_URL = null;
    $RESOURCE_ICON_URL = null;
    if ($PARSE_FULL_LIST) {
        $_GET['parse_full_list'] = '1';
    }
}

function fixture_normalize_value($value)
{
    if (!is_array($value)) {
        return $value;
    }
    $result = [];
    foreach ($value as $k => $v) {
        $result[$k] = fixture_normalize_value($v);
    }
    if (array_keys($result) !== range(0, count($result) - 1)) {
        ksort($result);
    }
    return $result;
}

function fixture_normalize_contests($contests, $ignore_fields = [])
{
    $normalized = [];
    foreach ($contests as $contest) {
        foreach ($ignore_fields as $field) {
            unset($contest[$field]);
        }
        $normalized[] = fixture_normalize_value($contest);
    }
    $sort_keys = [];
    foreach ($normalized as $idx => $contest) {
        $sort_keys[$idx] = json_encode($contest);
    }
    if (!empty($normalized)) {
        array_multisort($sort_keys, SORT_STRING, $normalized);
    }
    return $normalized;
}

function fixture_contests_to_json($contests)
{
    return json_encode($contests, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . "\n";
}

function fixture_exec_child($command, &$stdout, &$stderr)
{
    $descriptors = [
        0 => ['file', '/dev/null', 'r'],
        1 => ['pipe', 'w'],
        2 => ['pipe', 'w'],
    ];
    $process = proc_open($command, $descriptors, $pipes);
    if (!is_resource($process)) {
        die("failed to run: $command\n");
    }
    stream_set_blocking($pipes[1], 0);
    stream_set_blocking($pipes[2], 0);
    $stdout = '';
    $stderr = '';
    $read = [$pipes[1], $pipes[2]];
    $write = null;
    $except = null;
    while (count($read) > 0) {
        $r = $read;
        $w = $write;
        $e = $except;
        $num_changed_streams = stream_select($r, $w, $e, null);
        if ($num_changed_streams === false) {
            continue;
        }
        foreach ($r as $stream) {
            $data = fread($stream, 8192);
            if ($data !== false && $data !== '') {
                if ($stream === $pipes[1]) {
                    $stdout .= $data;
                } else {
                    $stderr .= $data;
                }
            }
            if (feof($stream)) {
                fclose($stream);
                $key = array_search($stream, $read);
                if ($key !== false) {
                    unset($read[$key]);
                }
            }
        }
    }
    return proc_close($process);
}

function fixture_module_command($fixture_dir, $mode, $use_faketime)
{
    $command = 'CURLEXEC_CACHE_MODE=' . escapeshellarg($mode);
    $command .= ' CURLEXEC_CACHE_DIR=' . escapeshellarg($fixture_dir . '/httpcache');
    $command .= ' TZ=UTC';
    if ($use_faketime) {
        $meta = fixture_load_meta($fixture_dir);
        static $faketime_path = null;
        if ($faketime_path === null) {
            $faketime_path = trim((string) shell_exec('command -v faketime')) ?: '';
        }
        if ($faketime_path !== '') {
            $command .= ' ' . escapeshellarg($faketime_path) . ' ' . escapeshellarg($meta['recorded_at']);
        } else {
            fwrite(STDERR, "warning: faketime not found, replaying with live clock (year-sensitive fixtures may fail)\n");
        }
    }
    $command .= ' ' . escapeshellarg(PHP_BINARY) . ' ' . escapeshellarg(__DIR__ . '/run_module.php') . ' ' . escapeshellarg($fixture_dir);
    return $command;
}

function fixture_print_diff($expected, $actual, $limit = 20)
{
    static $diff_cmd = null;
    if ($diff_cmd === null) {
        $diff_cmd = trim((string) shell_exec('command -v diff')) ?: '';
    }

    if ($diff_cmd === '') {
        echo "  outputs differ (install diffutils to see the diff)\n";
        return;
    }

    $temp_expected = tempnam(sys_get_temp_dir(), 'expected_');
    $temp_actual = tempnam(sys_get_temp_dir(), 'actual_');
    file_put_contents($temp_expected, $expected);
    file_put_contents($temp_actual, $actual);

    $cmd = escapeshellarg($diff_cmd) . ' -u ' . escapeshellarg($temp_expected) . ' ' . escapeshellarg($temp_actual);
    $output = trim((string) shell_exec($cmd));

    @unlink($temp_expected);
    @unlink($temp_actual);

    $lines = explode("\n", $output);
    if (count($lines) > 2 && strncmp($lines[0], '---', 3) === 0 && strncmp($lines[1], '+++', 3) === 0) {
        $lines = array_slice($lines, 2);
    }
    echo implode("\n", array_slice($lines, 0, $limit)) . "\n";
    if (count($lines) > $limit) {
        echo "  ... diff truncated\n";
    }
}

function fixture_rmdir_recursive($dir)
{
    foreach (scandir($dir) as $name) {
        if ($name === '.' || $name === '..') {
            continue;
        }
        $path = $dir . '/' . $name;
        if (is_dir($path) && !is_link($path)) {
            fixture_rmdir_recursive($path);
        } else {
            unlink($path);
        }
    }
    rmdir($dir);
}

function fixture_chown_recursive($dir, $uid, $gid)
{
    @chown($dir, $uid);
    @chgrp($dir, $gid);
    foreach (glob($dir . '/*') as $path) {
        if (is_dir($path)) {
            fixture_chown_recursive($path, $uid, $gid);
        } else {
            @chown($path, $uid);
            @chgrp($path, $gid);
        }
    }
}

function fixture_colorize($text, $color_code)
{
    if (php_sapi_name() === 'cli' && defined('STDOUT') && function_exists('stream_isatty') && stream_isatty(STDOUT)) {
        return "\033[" . $color_code . 'm' . $text . "\033[0m";
    }
    return $text;
}
