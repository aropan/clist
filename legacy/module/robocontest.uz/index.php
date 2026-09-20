<?php

require_once dirname(__FILE__) . '/../../config.php';

$contests_url = $URL;
$seen = [];

for ($n_page = 1; ; $n_page += 1) {
    $page_url = "$contests_url?finished=$n_page";
    $page = curlexec($page_url);

    preg_match_all('#<script[^>]*type="application/json"[^>]*>(?P<json>.*?)</script>#s', $page, $matches, PREG_SET_ORDER);
    $props = null;
    foreach ($matches as $match) {
        $data = json_decode($match['json'], true);
        if (is_array($data) && ($data['component'] ?? null) === 'Contest/Index') {
            $props = $data['props'] ?? null;
            break;
        }
    }
    if (!is_array($props)) {
        trigger_error("Failed to find contests Inertia data on $page_url", E_USER_WARNING);
        break;
    }

    $pagination = $props['oldPagination'] ?? null;
    if (
        !is_array($pagination)
        || !isset($pagination['current_page'], $pagination['last_page'])
        || (int) $pagination['current_page'] !== $n_page
        || (int) $pagination['last_page'] < $n_page
    ) {
        trigger_error("Invalid contests pagination on $page_url", E_USER_WARNING);
        break;
    }

    $groups = $n_page === 1 ? ['nextItems', 'currentItems', 'oldItems'] : ['oldItems'];
    foreach ($groups as $group) {
        $items = $props[$group] ?? null;
        if (!is_array($items)) {
            trigger_error("Failed to find $group on $page_url", E_USER_WARNING);
            break 2;
        }
        foreach ($items as $item) {
            if (!isset($item['id'], $item['name'], $item['startTime'], $item['endTime'], $item['url'])) {
                trigger_error("Incomplete contest item on $page_url", E_USER_WARNING);
                continue;
            }
            $key = (string) $item['id'];
            if (isset($seen[$key])) {
                continue;
            }
            $seen[$key] = true;

            $contests[] = [
                'start_time' => $item['startTime'],
                'end_time' => $item['endTime'],
                'title' => trim($item['name']),
                'url' => url_merge($contests_url, $item['url']),
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $key,
            ];
        }
    }

    if (!isset($_GET['parse_full_list']) || $n_page >= (int) $pagination['last_page']) {
        break;
    }
}
