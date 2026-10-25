<?php

global $contests, $URL, $HOST, $RID, $TIMEZONE, $PARSE_FULL_LIST;

require_once dirname(__FILE__) . '/../../config.php';

$parsed = [];
$rules = ['icpc' => 'icpc', 'cf' => 'cf', 'score' => 'scoring'];
for ($page = 1; ; ++$page) {
    $page_url = rtrim($URL, '/') . "/?page=$page&page_size=200";
    $response = curlexec($page_url, null, [
        'json_output' => true,
        'http_header' => ['Accept: application/json', 'Accept-Language: en'],
    ]);
    if (
        response_code() !== 200
        || ($response['status'] ?? null) !== 'ok'
        || !isset($response['data'], $response['pagesCount'])
    ) {
        trigger_error("Unexpected contests response on $page_url", E_USER_WARNING);
        return;
    }
    foreach ($response['data'] as $contest) {
        if (!isset($rules[$contest['rules']])) {
            trigger_error("Unknown rules '{$contest['rules']}' for contest {$contest['id']}", E_USER_WARNING);
            return;
        }
        $minutes = $contest['personal_minutes'] ?? $contest['duration_minutes'];
        $parsed[] = [
            'key' => (string) $contest['id'],
            'title' => trim($contest['title']),
            'url' => $contest['url'],
            'standings_url' => $contest['standings_url'],
            'start_time' => $contest['start_time'],
            'end_time' => $contest['end_time'],
            'duration_in_secs' => (int) ($minutes * 60),
            'kind' => $contest['kind'],
            'standings_kind' => $rules[$contest['rules']],
            'is_rated' => $contest['is_rated'] ? 'true' : 'false',
            'info' => ['parse' => $contest, 'writers' => $contest['authors']],
            'skip_check_time' => !empty($PARSE_FULL_LIST),
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
        ];
    }
    if ($page >= $response['pagesCount']) {
        break;
    }
}
$contests = array_merge($contests, $parsed);
