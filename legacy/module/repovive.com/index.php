<?php

global $contests, $HOST, $TIMEZONE, $RID;

require_once dirname(__FILE__) . '/../../config.php';

$page = curlexec($URL);

$data = '';
preg_match_all('#self\.__next_f\.push\((.*?)\)</script>#s', $page, $chunks);
foreach ($chunks[1] as $chunk) {
    $chunk = json_decode($chunk, true);
    if (isset($chunk[1]) && is_string($chunk[1])) {
        $data .= $chunk[1];
    }
}

preg_match_all(
    '#(?=\{"id":)(?P<json>\{(?:[^{}"]++|"(?:[^"\\\\]++|\\\\.)*"|(?&json))*\})#s',
    $data,
    $matches,
    PREG_SET_ORDER,
);

foreach ($matches as $match) {
    $contest = json_decode($match['json'], true);
    if (!isset($contest['id'], $contest['title'], $contest['startDate'], $contest['endDate'])) {
        continue;
    }

    $slug = $contest['urlSlug'] ?? '';
    if ($slug === '' || $slug === '$undefined') {
        $slug = $contest['contestNumber'];
    }

    $contests[] = [
        'start_time' => preg_replace('#^\$D#', '', $contest['startDate']),
        'end_time' => preg_replace('#^\$D#', '', $contest['endDate']),
        'title' => $contest['title'],
        'url' => url_merge($URL, '/contests/') . rawurlencode((string) $slug),
        'key' => $contest['id'],
        'kind' => $contest['contestType'] ?? null,
        'info' => ['parse' => $contest],
        'host' => $HOST,
        'timezone' => $TIMEZONE,
        'rid' => $RID,
    ];
}
