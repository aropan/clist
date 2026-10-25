<?php

global $contests, $HOST_URL, $HOST, $RID;

require_once dirname(__FILE__) . '/../../config.php';

$api_url = url_merge($HOST_URL, '/api/contests');

for ($page = 0; ; ++$page) {
    $page_url = "$api_url?page=$page&size=100";
    $response = curlexec($page_url, null, ['json_output' => true]);
    if (
        !is_array($response)
        || !isset($response['content'], $response['page'], $response['totalPages'])
        || !is_array($response['content'])
        || (int) $response['page'] !== $page
        || (int) $response['totalPages'] < 0
    ) {
        trigger_error("Unexpected contests response on $page_url", E_USER_WARNING);
        break;
    }

    foreach ($response['content'] as $contest) {
        if (
            !isset($contest['id'], $contest['name'], $contest['contestType'], $contest['startTime'], $contest['durationMinutes'])
            || strtotime($contest['startTime']) === false
            || !is_numeric($contest['durationMinutes'])
            || $contest['durationMinutes'] <= 0
        ) {
            trigger_error("Incomplete contest on $page_url", E_USER_WARNING);
            continue;
        }

        $title_parts = [];
        foreach (['editionName', 'name', 'gameName'] as $field) {
            $words = preg_split('/\s+/u', trim($contest[$field] ?? ''), -1, PREG_SPLIT_NO_EMPTY);
            $existing_title = ' ' . mb_strtolower(implode(' ', $title_parts)) . ' ';
            // Remove whole-word prefixes and suffixes already present in earlier parts.
            foreach (['prefix', 'suffix'] as $edge) {
                for ($length = count($words); $length > 0; --$length) {
                    $overlap = array_slice($words, $edge === 'prefix' ? 0 : -$length, $length);
                    if (str_contains($existing_title, ' ' . mb_strtolower(implode(' ', $overlap)) . ' ')) {
                        $words = $edge === 'prefix'
                            ? array_slice($words, $length)
                            : array_slice($words, 0, count($words) - $length);
                        break;
                    }
                }
            }
            if ($words) {
                $title_parts[] = implode(' ', $words);
            }
        }

        $kind = strtolower($contest['contestType']);
        $contests[] = [
            'start_time' => $contest['startTime'],
            'duration' => $contest['durationMinutes'],
            'title' => implode('. ', $title_parts),
            'url' => $HOST_URL,
            'key' => (string) $contest['id'],
            'kind' => $kind,
            'info' => ['parse' => $contest],
            'skip_check_time' => true,
            'host' => $HOST,
            'timezone' => 'UTC',
            'rid' => $RID,
        ];
    }

    if ($page + 1 >= (int) $response['totalPages']) {
        break;
    }
}
