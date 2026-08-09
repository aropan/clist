<?php

// Shared helpers for offline schedule parser fixtures (tests/record.php,
// tests/run.php, tests/run_module.php). This file must stay side-effect free
// on include and must not require config.php.

function fixture_fail($message)
{
    fwrite(STDERR, rtrim($message) . "\n");
    exit(1);
}

function fixture_resource_component($host)
{
    $component = str_replace('_', '%5F', rawurlencode((string) $host));
    return str_replace('%2F', '__', $component);
}

function fixture_load_meta($fixture_dir)
{
    $meta_file = $fixture_dir . '/meta.json';
    if (!file_exists($meta_file)) {
        fixture_fail("missing $meta_file");
    }
    $meta = json_decode(file_get_contents($meta_file), true);
    if (!is_array($meta)) {
        fixture_fail("invalid json in $meta_file");
    }
    foreach (['host', 'rid', 'path', 'url', 'parse_url', 'timezone', 'recorded_at'] as $field) {
        if (!array_key_exists($field, $meta)) {
            fixture_fail("missing '$field' in $meta_file");
        }
    }
    return $meta;
}

function fixture_find_meta_files($fixtures_dir)
{
    if (!is_dir($fixtures_dir)) {
        return [];
    }

    $meta_files = [];
    $iterator = new RecursiveIteratorIterator(
        new RecursiveDirectoryIterator($fixtures_dir, FilesystemIterator::SKIP_DOTS),
    );
    foreach ($iterator as $file) {
        if ($file->getFilename() !== 'meta.json') {
            continue;
        }
        $relative_path = substr($file->getPathname(), strlen($fixtures_dir) + 1);
        if (preg_match('#(?:^|/)\.recording-#', $relative_path)) {
            continue;
        }
        $relative_dir = dirname($relative_path);
        $meta = fixture_load_meta($file->getPath());
        $expected_dir = fixture_resource_component($meta['host']);
        if ($relative_dir !== $expected_dir) {
            fixture_fail("fixture for {$meta['host']} must be stored in $fixtures_dir/$expected_dir");
        }
        $meta_files[] = $file->getPathname();
    }
    sort($meta_files, SORT_STRING);
    return $meta_files;
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

function fixture_normalize_field_name($field)
{
    $field = preg_replace('/([a-z0-9])([A-Z])/', '$1_$2', (string) $field);
    $field = preg_replace('/[^a-z0-9]+/i', '_', $field);
    return strtolower(trim($field, '_'));
}

function fixture_is_sensitive_field_name($field)
{
    $field = fixture_normalize_field_name($field);
    if (preg_match('/(?:^|_)(?:password|passwd|pwd)(?:_|$)/', $field)) {
        return true;
    }
    if (preg_match('/(?:^|_)(?:access|refresh|auth|api|private|client|secret|bearer)_(?:token|key|secret|sig|signature)(?:_|$)/', $field)) {
        return true;
    }
    if (preg_match('/(?:^|_)(?:token|secret|authorization)(?:s)?$/', $field)) {
        return true;
    }
    if ($field === 'session' || preg_match('/_(?:session|session_id|session_token)$/', $field)) {
        return true;
    }
    return $field === 'cookie' || preg_match('/_(?:cookie|cookies)$/', $field);
}

function fixture_json_path($path, $key)
{
    if (is_int($key)) {
        return $path . '[' . $key . ']';
    }
    if (preg_match('/^[A-Za-z_][A-Za-z0-9_]*$/', $key)) {
        return $path . '.' . $key;
    }
    return $path . '[' . json_encode((string) $key) . ']';
}

function fixture_sensitive_field_allowed($relative_path, $json_path, $meta)
{
    foreach (isset($meta['allowed_sensitive_fields']) ? $meta['allowed_sensitive_fields'] : [] as $rule) {
        if (!is_array($rule) || !isset($rule['file']) || !isset($rule['path'])) {
            continue;
        }
        if (fnmatch($rule['file'], $relative_path) && fnmatch($rule['path'], $json_path)) {
            return true;
        }
    }
    return false;
}

function fixture_sensitive_environment_values()
{
    static $values = null;
    if ($values !== null) {
        return $values;
    }

    $values = [];
    foreach (getenv() as $key => $value) {
        $normalized_key = fixture_normalize_field_name($key);
        $sensitive_key = fixture_is_sensitive_field_name($key) || preg_match('/_(?:conf|credentials)$/', $normalized_key);
        if (!$sensitive_key || !is_string($value) || strlen($value) < 8) {
            continue;
        }
        $values[$key] = $value;
    }
    return $values;
}

function fixture_find_sensitive_text($content)
{
    foreach (fixture_sensitive_environment_values() as $key => $value) {
        if (strpos($content, $value) !== false) {
            return "contains the value of environment variable $key";
        }
    }

    $authorization_pattern = '/(?:^|\r?\n)(?:authorization|proxy-authorization)\s*:\s*(?:bearer|basic)\s+[^\s<]+/i';
    if (preg_match($authorization_pattern, $content)) {
        return 'contains an authorization header';
    }
    $content_without_redacted_cookies = preg_replace(
        '/(?:^|\r?\n)set-cookie\s*:\s*[^=;\r\n]+=<redacted>(?:;[^\r\n]*)?/i',
        '',
        $content,
    );
    if (preg_match('/(?:^|\r?\n)set-cookie\s*:/i', $content_without_redacted_cookies)) {
        return 'contains a Set-Cookie header';
    }
    $content = $content_without_redacted_cookies;
    if (preg_match('#\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@#i', $content)) {
        return 'contains credentials in a URL';
    }

    $name_pattern = '(?:password|passwd|pwd|access[_-]?token|refresh[_-]?token|auth[_-]?token|api[_-]?(?:key|sig|signature)|client[_-]?secret|session(?:[_-]?(?:id|token))?|cookie|authorization)';
    $assignment_pattern = '/\b(' . $name_pattern . ')\b["\']?\s*[:=]\s*["\']?[^\s"\'&<>,;]{8,}/i';
    if (preg_match($assignment_pattern, $content, $match)) {
        return 'contains a credential-like assignment for ' . fixture_normalize_field_name($match[1]);
    }
    return null;
}

function fixture_find_sensitive_json($value, $relative_path, $meta, $json_path = '$')
{
    if (is_string($value)) {
        $issue = fixture_find_sensitive_text($value);
        return $issue === null ? null : "$json_path $issue";
    }
    if (!is_array($value)) {
        return null;
    }

    foreach ($value as $key => $child) {
        $child_path = fixture_json_path($json_path, $key);
        if (
            !is_int($key)
            && fixture_is_sensitive_field_name($key)
            && !is_bool($child)
            && $child !== null
            && !fixture_sensitive_field_allowed($relative_path, $child_path, $meta)
        ) {
            return "sensitive JSON field $child_path";
        }
        if (fixture_sensitive_field_allowed($relative_path, $child_path, $meta)) {
            continue;
        }
        $issue = fixture_find_sensitive_json($child, $relative_path, $meta, $child_path);
        if ($issue !== null) {
            return $issue;
        }
    }
    return null;
}

function fixture_sanitize_public_text($content)
{
    $content = preg_replace_callback(
        '/(?<![\w.+-])[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])/i',
        function ($match) {
            $email = $match[0];
            $public_suffix = '@group.calendar.google.com';
            if (substr(strtolower($email), -strlen($public_suffix)) === $public_suffix) {
                return $email;
            }
            return '<redacted-email>';
        },
        $content,
    );
    $content = preg_replace(
        '/\btel:\s*\+?(?:[ ()-]*\d){7,15}/i',
        'tel:<redacted-phone>',
        $content,
    );
    $content = preg_replace(
        '/(?<![A-Za-z0-9])\+(?:[ ()-]*\d){7,15}(?![A-Za-z0-9])/',
        '<redacted-phone>',
        $content,
    );
    $content = preg_replace('/\bAIza[0-9A-Za-z_-]{30,}\b/', '<redacted-google-api-key>', $content);
    return preg_replace(
        '/("testSessionHandle"\s*:\s*")[^"]*(")/',
        '$1<redacted-test-session-handle>$2',
        $content,
    );
}

function fixture_sanitize_recording($fixture_dir)
{
    $sanitized = 0;
    $iterator = new RecursiveIteratorIterator(
        new RecursiveDirectoryIterator($fixture_dir, FilesystemIterator::SKIP_DOTS),
    );
    foreach ($iterator as $file) {
        if (!$file->isFile()) {
            continue;
        }
        $path = $file->getPathname();
        $compressed = substr($path, -3) === '.gz';
        $content = file_get_contents($path);
        if ($compressed) {
            $content = gzdecode($content);
            if ($content === false) {
                throw new RuntimeException("invalid gzip file $path");
            }
        }
        $sanitized_content = fixture_sanitize_public_text($content);
        if ($sanitized_content === $content) {
            continue;
        }
        file_put_contents($path, $compressed ? gzencode($sanitized_content, 9) : $sanitized_content);
        $sanitized += 1;
    }
    return $sanitized;
}

function fixture_validate_content($content, $relative_path, $meta)
{
    if (fixture_sanitize_public_text($content) !== $content) {
        return 'contains an email address, phone number, browser API key, or test session handle';
    }
    $decoded = json_decode($content, true);
    if (json_last_error() === JSON_ERROR_NONE) {
        return fixture_find_sensitive_json($decoded, $relative_path, $meta);
    }
    return fixture_find_sensitive_text($content);
}

function fixture_validate_recording($fixture_dir)
{
    $meta = fixture_load_meta($fixture_dir);
    $iterator = new RecursiveIteratorIterator(
        new RecursiveDirectoryIterator($fixture_dir, FilesystemIterator::SKIP_DOTS),
    );
    foreach ($iterator as $file) {
        if (!$file->isFile()) {
            continue;
        }
        $relative_path = substr($file->getPathname(), strlen($fixture_dir) + 1);
        $content = file_get_contents($file->getPathname());
        if (substr($relative_path, -3) === '.gz') {
            $content = gzdecode($content);
            if ($content === false) {
                throw new RuntimeException("invalid gzip file $relative_path");
            }
        }
        $issue = fixture_validate_content($content, $relative_path, $meta);
        if ($issue !== null) {
            throw new RuntimeException("refusing to keep a potential credential in $relative_path: $issue");
        }
    }
}

function fixture_find_direct_network_call($module_dir)
{
    $functions = [
        'curl_exec',
        'curl_init',
        'curl_multi_exec',
        'fsockopen',
        'get_headers',
        'pfsockopen',
        'stream_socket_client',
    ];
    $iterator = new RecursiveIteratorIterator(
        new RecursiveDirectoryIterator($module_dir, FilesystemIterator::SKIP_DOTS),
    );
    foreach ($iterator as $file) {
        if (!$file->isFile() || $file->getExtension() !== 'php') {
            continue;
        }
        $tokens = token_get_all(file_get_contents($file->getPathname()));
        foreach ($tokens as $idx => $token) {
            if (!is_array($token) || $token[0] !== T_STRING || !in_array(strtolower($token[1]), $functions)) {
                continue;
            }
            for ($next = $idx + 1; $next < count($tokens); ++$next) {
                if (is_array($tokens[$next]) && in_array($tokens[$next][0], [T_WHITESPACE, T_COMMENT, T_DOC_COMMENT])) {
                    continue;
                }
                if ($tokens[$next] === '(') {
                    $relative_path = substr($file->getPathname(), strlen($module_dir) + 1);
                    return "$relative_path:{$token[2]} calls {$token[1]}() directly";
                }
                break;
            }
        }
    }
    return null;
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
        fixture_fail("failed to run: $command");
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
            fixture_fail('faketime is required for deterministic schedule fixture replay');
        }
    }
    $command .= ' ' . escapeshellarg(PHP_BINARY) . ' -d allow_url_fopen=0';
    $command .= ' ' . escapeshellarg(__DIR__ . '/run_module.php') . ' ' . escapeshellarg($fixture_dir);
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
