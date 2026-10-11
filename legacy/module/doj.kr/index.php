<?php

require_once dirname(__FILE__) . '/../../config.php';

global $URL, $HOST, $RID, $TIMEZONE, $contests;

$parse_full_list = isset($_GET['parse_full_list']);
$statuses = $parse_full_list ? ['all'] : ['upcoming', 'running', 'ended'];
foreach ($statuses as $status) {
    $cursor = null;
    $seen_cursors = [];
    do {
        $params = ['status' => $status, 'limit' => $parse_full_list ? 100 : 20];
        if ($cursor !== null) {
            $params['cursor'] = $cursor;
        }
        $url = $URL . '?' . http_build_query($params);
        $data = curlexec($url, null, ['json_output' => true]);
        if (!is_array($data) || !isset($data['contests'])) {
            trigger_error('Failed to fetch DOJ contests', E_USER_WARNING);
            break;
        }
        foreach ($data['contests'] as $contest) {
            $duration = strtotime($contest['endAt']) - strtotime($contest['startAt']);
            if ($contest['windowed']) {
                $duration = $contest['windowDurationSeconds'] ?? $contest['windowDurationMinutes'] * 60;
            }
            $contests[] = [
                'start_time' => $contest['startAt'],
                'end_time' => $contest['endAt'],
                'duration_in_secs' => $duration,
                'title' => $contest['title'],
                'url' => url_merge($URL, '/en/contests/' . rawurlencode($contest['slug'])),
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $contest['slug'],
                'info' => ['parse' => $contest],
            ];
        }
        if ($status === 'ended') {
            break;
        }
        $cursor = $data['nextCursor'] ?? null;
        if ($cursor !== null) {
            if (isset($seen_cursors[$cursor])) {
                trigger_error('Repeated DOJ contest cursor', E_USER_WARNING);
                break;
            }
            $seen_cursors[$cursor] = true;
        }
    } while ($cursor !== null);
}
