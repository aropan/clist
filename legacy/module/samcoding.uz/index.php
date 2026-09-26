<?php

global $contests, $URL, $HOST, $RID, $TIMEZONE;

require_once dirname(__FILE__) . '/../../config.php';

for ($page = 1; ; ++$page) {
    $page_url = "$URL?page=$page";
    $response = curlexec($page_url, null, ['json_output' => true]);
    if (
        !is_array($response)
        || !isset($response['data'], $response['page'], $response['pagesCount'])
        || !is_array($response['data'])
        || (int) $response['page'] !== $page
        || (int) $response['pagesCount'] < $page
    ) {
        trigger_error("Unexpected contests response on $page_url", E_USER_WARNING);
        break;
    }

    foreach ($response['data'] as $contest) {
        if (!isset($contest['id'], $contest['title'], $contest['start_time'], $contest['end_time'], $contest['url'])) {
            trigger_error("Incomplete contest on $page_url", E_USER_WARNING);
            continue;
        }

        $contests[] = [
            'start_time' => $contest['start_time'],
            'end_time' => $contest['end_time'],
            'title' => trim($contest['title']),
            'url' => $contest['url'],
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => (string) $contest['id'],
        ];
    }

    if (!isset($_GET['parse_full_list']) || $page >= (int) $response['pagesCount']) {
        break;
    }
}
