<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $urls = array($URL, 'https://hackerrank.com/rest/contests/college');
    $limit = 50;
    $offset = 0;
    $seen = array();
    foreach ($urls as $base_url) {
        for (;;) {
            $url = "$base_url?limit=$limit&offset=$offset";
            $json = curlexec($url, NULL, array('json_output' => true));
            if (!is_array($json) || !is_array($json['models'])) {
                var_dump($json);
                trigger_error("Expected array ['models']", E_USER_WARNING);
                break;
            }

            $n_added = 0;
            foreach ($json['models'] as $model)
            {
                $key = $model['id'];
                if (isset($seen[$key])) {
                    continue;
                }
                $seen[$key] = true;
                $n_added += 1;

                $kind = isset($model['track'])? $model['track']['slug'] : null;

                $contests[] = array(
                    'start_time' => date('r', $model['epoch_starttime']),
                    'end_time' => date('r', $model['epoch_endtime']),
                    'title' => $model['name'],
                    'url' => 'https://hackerrank.com/contests/' . $model['slug'],
                    'host' => $HOST,
                    'rid' => $RID,
                    'timezone' => 'UTC',
                    'kind' => $kind,
                    'key' => $key,
                    'info' => array('parse' => $model),
                );
            }

            if (!isset($_GET['parse_full_list']) || !$n_added) {
                break;
            }
            $offset += $limit;
        }
    }

    $url = 'https://hackerrank.com/api/hrw/resources/competitions?filter%5Bstatus%5D=published';
    $seen = array();
    while ($url && !isset($seen[$url])) {
        $seen[$url] = true;
        $json = curlexec($url, NULL, array('json_output' => true));
        if (!is_array($json) || !is_array($json['data'])) {
            var_dump($json);
            trigger_error("Expected array ['data']", E_USER_WARNING);
        } else {
            foreach ($json['data'] as $c) {
                $attrs = $c['attributes'];
                $contests[] = array(
                    'start_time' => $attrs['starts_at'],
                    'end_time' => $attrs['ends_at'],
                    'title' => $attrs['name'],
                    'url' => 'https://hackerrank.com/competitions/' . $attrs['slug'],
                    'host' => $HOST,
                    'rid' => $RID,
                    'timezone' => 'UTC',
                    'key' => 'competitions/' . $c['id'],
                );
            }
        }
        if (!isset($json['links']) || !isset($json['links']['next'])) {
            break;
        }
        $url = $json['links']['next'];
    }


    if ($RID == -1) {
        print_r($contests);
    }
?>
