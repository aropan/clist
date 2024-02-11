<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $url = 'https://codeany.org/api/competitions/list';
    $seen = array();
    for ($n_page = 1; ; $n_page += 1) {
        $url = url_merge($url, "?format=json&page=$n_page");
        $data = curlexec($url, NULL, array('json_output' => true));

        if (!is_array($data['list_competitions'])) {
            break;
        }

        $n_added = 0;
        foreach ($data['list_competitions'] as $c) {
            $key = $c['id'];
            if (isset($seen[$key])) {
                continue;
            }
            $seen[$key] = true;
            $n_added += 1;
            $contests[] = array(
                'start_time' => $c['time_begin'],
                'duration' => $c['length'],
                'title' => $c['titles']['en'],
                'url' => "https://codeany.org/competition/$key",
                'kind' => strtolower($c['type']),
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $key,
            );
        }
        if (!$n_added || !isset($_GET['parse_full_list'])) {
            break;
        }
    }
?>
