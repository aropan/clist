<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $page = 0;
    for (;;) {
        $page += 1;
        $url = "$URL?page=$page&_contentOnly";
        $data = curlexec($url, null, ['json_output' => true]);
        $contests_data = pop_item($data, ['currentData', 'contests', 'result']);
        $contests_info = pop_item($data, ['currentData', 'contests']);
        if (!$contests_data || !$contests_info) {
            trigger_error('Failed to parse contests data = ' . json_encode($data), E_USER_WARNING);
            break;
        }
        $total_pages = $contests_info['perPage']? $contests_info['count'] / $contests_info['perPage'] : 0;

        foreach ($contests_data as $c) {
            $key = array_pop_assoc($c, 'id');
            $title = trim(array_pop_assoc($c, 'name'));
            $kind = null;
            $standings_kind = null;

            $rule_type = array_pop_assoc($c, 'ruleType');
            if ($rule_type == 2) {
                $kind = 'ICPC';
                $standings_kind = 'icpc';
            } elseif ($rule_type == 4) {
                $kind = 'IOI';
                $standings_kind = 'scoring';
            } elseif ($rule_type == 1) {
                $kind = 'OI';
                $standings_kind = 'scoring';
            } elseif ($rule_type == 5) {
                $kind = 'CF';
                $standings_kind = 'cf';
            } elseif ($rule_type == 3) {
                $kind = 'LEDO';
                $standings_kind = 'scoring';
            } else {
                $c['ruleType'] = $rule_type;
            }

            $tags = [];
            if (array_pop_assoc($c, 'rated')) {
                $tags[] = 'rated';
            }
            if ($kind) {
                $tags[] = strtolower($kind);
            }

            if ($tags) {
                $title .= ' [' . implode(', ', $tags) . ']';
            }

            $contests[] = array(
                'start_time' => array_pop_assoc($c, 'startTime'),
                'end_time' => array_pop_assoc($c, 'endTime'),
                'title' => $title,
                'url' => url_merge($URL, '/contest/' . $key),
                'rid' => $RID,
                'host' => $HOST,
                'timezone' => $TIMEZONE,
                'standings_kind' => $standings_kind,
                'key' => $key,
                'info' => ['parse' => $c],
            );
        }

        if ($page >= $total_pages || !isset($_GET['parse_full_list'])) {
            break;
        }
    }
?>
